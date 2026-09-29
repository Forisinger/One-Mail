# -*- coding: utf-8 -*-
"""已读状态同步（v1.7.0）：本地标已读后，把 \\Seen 写回服务器。

设计要点：
- 收信通道永远 readonly（安全红线不变）；本模块用独立的**短连接**（连上→STORE→logout）
  改标志，与收信长连接完全隔离，互不污染 socket。
- UI 线程只投递任务（submit），网络操作全部在后台线程，永不阻塞界面。
- 任务按 (account, folder, seen) 分组、UID 数值排序、50 个一批成批 STORE——
  "全部已读"也是每 (账户, 文件夹) 一次连接，绝不每封一连。
- 失败按块重试 1 次后丢弃：已读同步是幂等操作，丢弃无害（下次标记会再触发），
  无限重试反而会堆积任务、反复打扰服务器。
- 任何异常路径都必须释放去重键（_forget）：宁可少同步一封（幂等、可再触发），
  也不能让键泄漏导致该邮件的后续同步请求被永久静默吞掉。
- connector / get_credentials / enabled 全部可注入 → 核心逻辑可离线单测。

已知接受的边界：seen 方向反转的窄竞态（标已读→立刻标未读）理论上可能以
后到的写回收尾；当前 UI 只有"标已读"入口，出现概率可忽略，暂不为此加序号机制。
"""
from __future__ import annotations

import queue
import threading
from typing import Any, Callable

# 单个 STORE 命令的 UID 数上限：seq-set 过长可能被服务器拒绝
CHUNK_SIZE = 50
# worker 每轮最多合并的任务数（防单批过大拖住后续任务）
BATCH_LIMIT = 500


class FlagSync:
    """把本地已读/未读变化异步写回 IMAP 服务器的后台工作器。

    get_credentials(account_id) -> (Account | None, password | None)
    connector(account, password, folder, uids, seen)   默认 MailClient.mark_seen
    enabled() -> bool                                  总开关（config 读取）
    log(msg) -> None                                   日志落盘
    start_thread=False 时不启动工作线程（单测直接调 _process_batch）。
    """

    def __init__(self,
                 get_credentials: Callable[[str], tuple[Any | None, str | None]],
                 connector: Callable | None = None,
                 enabled: Callable[[], bool] | None = None,
                 log: Callable[[str], None] | None = None,
                 start_thread: bool = True):
        from core.mail_client import MailClient   # 延迟导入，方便测试注入
        self._get_credentials = get_credentials
        self._connector = connector or MailClient.mark_seen
        self._enabled = enabled or (lambda: True)
        self._log = log or (lambda msg: None)

        self._queue: queue.Queue = queue.Queue()
        self._pending: set[tuple] = set()    # 去重：(account_id, folder, uid, seen)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        if start_thread:
            self._thread = threading.Thread(
                target=self._run, name="onemail-flagsync", daemon=True)
            self._thread.start()

    # ---------- UI 线程接口 ----------
    def submit(self, account_id: str, folder: str, uid, seen: bool = True) -> None:
        self.submit_many([(account_id, folder, uid, seen)])

    def submit_many(self, jobs) -> None:
        """jobs: (account_id, folder, uid, seen) 序列。去重后入队，永不抛错。"""
        try:
            for account_id, folder, uid, seen in jobs:
                if not account_id or not uid:
                    continue
                key = (account_id, folder or "INBOX", str(uid), bool(seen))
                with self._lock:
                    if key in self._pending:
                        continue
                    self._pending.add(key)
                self._queue.put((key[0], key[1], key[2], key[3], 0))  # 0=attempts
        except Exception as e:
            self._log(f"flag_sync 投递异常: {e!r}")

    # ---------- 后台线程 ----------
    def _run(self):
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            batch = [job]
            while len(batch) < BATCH_LIMIT:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            try:
                self._process_batch(batch)
            except Exception as e:
                # 兜底防线：处理失败时也必须释放去重键，否则这些邮件的
                # 后续同步请求会被 _pending 永久拦截（且无自愈）
                self._log(f"flag_sync 批处理异常（对应任务已丢弃）: {e!r}")
                with self._lock:
                    for account_id, folder, uid, seen, _ in batch:
                        self._pending.discard(
                            (account_id, folder, str(uid), bool(seen)))

    def _process_batch(self, jobs: list[tuple]) -> None:
        """按 (account, folder, seen) 分组逐组处理。可注入 connector 直接单测。"""
        groups: dict[tuple[str, str, bool], list[tuple[str, int]]] = {}
        for account_id, folder, uid, seen, attempts in jobs:
            groups.setdefault((account_id, folder, bool(seen)), []).append(
                (str(uid), attempts))
        for (account_id, folder, seen), uid_list in groups.items():
            try:
                self._process_group(account_id, folder, seen, uid_list)
            except Exception as e:
                # 单组异常不拖垮其余组；本组释放键防泄漏
                self._log(f"flag_sync: 组处理异常（已丢弃）: {e!r}")
                self._forget(account_id, folder,
                             [u for u, _ in uid_list], seen)

    def _process_group(self, account_id: str, folder: str, seen: bool,
                       uid_list: list[tuple[str, int]]) -> None:
        # 非数字 UID 无法组成合法 seq-set：剔除并记日志（历史脏数据防御）
        all_uids = [u for u, _ in uid_list]
        uids = sorted({u for u in all_uids if u.isdigit()}, key=int)
        bad = set(all_uids) - set(uids)
        if bad:
            self._log(f"flag_sync: 非法 UID 已剔除: {sorted(bad)[:5]}")
        if not uids:
            self._forget(account_id, folder, all_uids, seen)
            return
        attempts = max(a for _, a in uid_list)

        # 以下任何提前返回路径都必须先释放去重键
        try:
            if not self._enabled():
                self._forget(account_id, folder, uids, seen)
                return
            try:
                account, password = self._get_credentials(account_id)
            except Exception as e:
                self._log(f"flag_sync: 取账户凭据异常（任务丢弃）: {e!r}")
                self._forget(account_id, folder, uids, seen)
                return
            if account is None or not password:
                self._log(f"flag_sync: 账户 {account_id} 缺失/无授权码，"
                          f"{len(uids)} 个同步任务丢弃")
                self._forget(account_id, folder, uids, seen)
                return
        except Exception as e:
            self._log(f"flag_sync: 前置检查异常（任务丢弃）: {e!r}")
            self._forget(account_id, folder, uids, seen)
            return

        # 块级失败收集：成功块不重发（幂等但省流量）
        failed: list[str] = []
        err: Exception | None = None
        for i in range(0, len(uids), CHUNK_SIZE):
            chunk = uids[i:i + CHUNK_SIZE]
            try:
                self._connector(account, password, folder, chunk, seen)
            except Exception as e:
                failed.extend(chunk)
                err = e
        if not failed:
            self._forget(account_id, folder, uids, seen)
            return
        self._log(f"flag_sync: {getattr(account, 'email', account_id)} "
                  f"{folder} 同步 {'已读' if seen else '未读'} 失败"
                  f"（{len(failed)}/{len(uids)} 封）: "
                  f"{type(err).__name__}: {err}")
        if attempts < 1:
            # 重试失败块一次；成功块立即释放键
            ok = [u for u in uids if u not in set(failed)]
            self._forget(account_id, folder, ok, seen)
            for u in failed:
                self._queue.put((account_id, folder, u, seen, attempts + 1))
        else:
            self._log("flag_sync: 重试仍失败，任务丢弃（幂等，无丢失风险）")
            self._forget(account_id, folder, uids, seen)

    def _forget(self, account_id: str, folder: str, uids, seen: bool) -> None:
        with self._lock:
            for uid in uids:
                self._pending.discard((account_id, folder, str(uid), seen))

    def stop(self) -> None:
        self._stop.set()
