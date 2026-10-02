# -*- coding: utf-8 -*-
"""IMAP 收信客户端：IDLE 推送为主，轮询降级，指数退避重连。

资源占用核心：
- IDLE 长连接阻塞在 socket 上等待服务器推送，空闲 CPU ≈ 0
- RFC 2177 要求 IDLE 最长 29 分钟，这里 24 分钟主动 DONE 重发保活
- 断线重连采用指数退避（5s 起，上限 10min），避免疯狂重试烧 CPU
"""
from __future__ import annotations

import base64
import imaplib
import re
import select
import socket
import threading
import time
import traceback

from .parser import parse_raw
from storage import database

_IMAP4_PORT_SSL = 993
_IDLE_REFRESH = 24 * 60          # IDLE 保活周期（秒）
_SELECT_SLICE = 2                # IDLE 等待分片（秒）：唤醒/停止的最大延迟
_RECONNECT_BASE = 5              # 重连退避起点（秒）
_RECONNECT_MAX = 10 * 60
_CONNECT_TIMEOUT = 15            # IMAP 建连超时（秒），含 list_folders

# 从 IDLE 未请求响应里抓邮箱状态行（如 * 23 EXISTS）
_EXISTS_RE = re.compile(rb"\*\s+(\d+)\s+EXISTS", re.IGNORECASE)


def imap_login(conn, account, password: str) -> None:
    """按账户认证方式登录 IMAP：密码登录 or OAuth2 XOAUTH2（v1.10.0）。

    OAuth2 账户忽略 password 参数，凭据取自 DPAPI 存储的令牌（自动刷新）；
    OAuth2Error 统一包装成 imaplib.IMAP4.error，走既有的重连/报错通道。
    """
    if getattr(account, "auth_type", "password") == "oauth2":
        from .oauth2 import OAuth2Error, get_access_token, imap_authenticate
        try:
            token = get_access_token(account)
        except OAuth2Error as e:
            raise imaplib.IMAP4.error(f"OAuth2: {e}") from e
        try:
            imap_authenticate(conn, account, token)
        except OAuth2Error as e:
            raise imaplib.IMAP4.error(f"OAuth2: {e}") from e
    else:
        conn.login(account.email, password)

# imaplib 不内置 ID 命令；163/126 等国内服务器要求登录后上报客户端身份，
# 否则后续命令可能被服务端拒绝/踢线。声明后才能用 _simple_command 发送。
imaplib.Commands["ID"] = ("AUTH", "SELECTED")


class MailClient:
    """单个邮箱账户的收信守护线程。

    on_new_mail(account, [ParsedMail])  —— 收到新邮件回调（调度器注入）
    on_status(account, text)            —— 连接状态变化回调
    """

    def __init__(self, account, password: str, on_new_mail, on_status):
        self.account = account
        self.password = password
        self._on_new_mail = on_new_mail
        self._on_status = on_status
        self._stop = threading.Event()
        self._wake = threading.Event()   # 「立即收信」唤醒信号
        self._thread: threading.Thread | None = None
        self._conn: imaplib.IMAP4 | None = None   # 供 stop() 关 socket 打断阻塞
        self._failed_uids: set[str] = set()  # 单封失败记忆：二次失败跳过防队头阻塞

    # ---------- 生命周期 ----------
    def start(self):
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name=f"mail-{self.account.email}", daemon=True
        )
        self._thread.start()

    def stop(self):
        """请求停止。收信线程可能阻塞在 read 上，直接关 socket 让它立刻退出。"""
        self._stop.set()
        self._wake.set()
        conn = self._conn
        if conn is not None:
            try:
                conn.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                conn.sock.close()
            except OSError:
                pass

    def wake(self):
        """请求立即收信一次（打断 IDLE 等待/轮询睡眠）。"""
        self._wake.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    # ---------- 主循环 ----------
    def _run_loop(self):
        backoff = _RECONNECT_BASE
        while not self._stop.is_set():
            conn = None
            try:
                conn = self._connect()
                self._conn = conn
                self._status("已连接")
                backoff = _RECONNECT_BASE
                if self._probe_idle(conn):
                    self._idle_loop(conn)
                else:
                    self._status("服务器不支持 IDLE，转为轮询")
                    self._poll_loop(conn)
            except (imaplib.IMAP4.error, socket.error, OSError) as e:
                text = f"{type(e).__name__}: {e}"
                # OAuth2 令牌失效（改密/吊销/长期闲置）：重试无意义，
                # 顶格退避并给出明确引导（v1.10.1）
                if "OAuth2" in text and ("重新登录" in text
                                         or "invalid_grant" in text):
                    self._status("OAuth2 令牌已失效，请编辑账户重新登录")
                    backoff = _RECONNECT_MAX
                else:
                    self._status(f"连接异常：{text}，{backoff}s 后重连")
            except Exception:  # 未知异常也绝不退出线程
                self._status("未知错误，稍后重连")
                traceback.print_exc()
            finally:
                self._conn = None
                if conn is not None:
                    try:
                        conn.logout()
                    except Exception:
                        pass
            # 退避等待（可被 stop 立即打断）
            if self._stop.wait(backoff):
                break
            backoff = min(backoff * 2, _RECONNECT_MAX)

    # ---------- 连接 ----------
    def _connect(self) -> imaplib.IMAP4:
        acc = self.account
        if acc.ssl:
            conn = imaplib.IMAP4_SSL(acc.imap_host, acc.imap_port,
                                     timeout=_CONNECT_TIMEOUT)
        else:
            conn = imaplib.IMAP4(acc.imap_host, acc.imap_port,
                                 timeout=_CONNECT_TIMEOUT)
        imap_login(conn, acc, self.password)
        self._send_client_id(conn)      # 163/126：必须上报客户端 ID
        conn.select(self._folder_wire(), readonly=True)
        return conn

    def _folder(self) -> str:
        """收信文件夹名（空值回退 INBOX）。"""
        return (getattr(self.account, "folder", "") or "INBOX").strip() or "INBOX"

    def _folder_wire(self) -> str:
        """IMAP 协议层的文件夹名（见模块级 folder_to_wire）。"""
        return folder_to_wire(self._folder())

    @staticmethod
    def _send_client_id(conn) -> None:
        """发送 IMAP ID 扩展命令。失败不影响连接（部分服务器不支持）。"""
        try:
            conn._simple_command("ID", '("name" "OneMail" "version" "1.0")')
            conn._untagged_response("OK", [], "ID")
        except Exception:
            pass

    def _probe_idle(self, conn) -> bool:
        """探测服务器是否支持 IDLE，并记录探测结果。"""
        if self.account.idle_supported is not None:
            return self.account.idle_supported
        supported = self._idle_supported(conn)
        self.account.idle_supported = supported
        return supported

    @staticmethod
    def _idle_supported(conn) -> bool:
        try:
            typ, caps = conn.capability()
            if typ != "OK":
                return False
            caps_str = b" ".join(caps).decode("ascii", "ignore").upper()
            return "IDLE" in caps_str.split()
        except Exception:
            return False

    # ---------- IDLE 推送模式 ----------
    def _idle_loop(self, conn):
        typ, _data = conn.select(self._folder_wire(), readonly=True)
        if typ != "OK":
            raise imaplib.IMAP4.error(f"SELECT {self._folder()} failed")
        # 启动即全量对账一次（补收离线期间的邮件）
        self._fetch_new(conn)

        while not self._stop.is_set():
            got_event = self._idle_wait(conn, _IDLE_REFRESH)
            if self._stop.is_set():
                break
            if not got_event and self.account.idle_supported is False:
                # IDLE 实际不可用（探测阶段没发现），退出让上层转轮询
                return
            if conn.state != "SELECTED":
                raise imaplib.IMAP4.abort(
                    f"连接已被服务器关闭(state={conn.state})")
            if got_event:
                self._status("收到新邮件推送")
            elif self._wake.was_set():
                self._status("手动收信")
            self._wake.clear()
            self._fetch_new(conn)

    def _idle_wait(self, conn, timeout: float) -> bool:
        """进入 IDLE 等待。返回 True 表示服务器推送了 EXISTS（可能有新邮件）。

        用 select.select 分片等待，**绝不**对 socket settimeout——imaplib 的
        文件对象一旦发生超时就被永久污染（SocketIO._timeout_occurred），
        之后任何 read 都会抛 OSError，导致每个保活周期必然断线重连。
        分片同时检查 _stop/_wake，停止与「立即收信」即时生效（≤2s）。
        """
        tag = conn._new_tag().decode()
        conn.send(f"{tag} IDLE\r\n".encode())
        # 继续行（+ ...）之前可能先到 untagged 行（如恰好抵达的 EXISTS）；
        # 有界等待而非无限阻塞，超时按不支持 IDLE 处理（转轮询）
        resp = b""
        cont_deadline = time.monotonic() + 10
        while time.monotonic() < cont_deadline and not self._stop.is_set():
            r, _, _ = select.select([conn.sock], [], [], _SELECT_SLICE)
            if not r:
                continue
            resp = conn.readline()
            if not resp:
                raise imaplib.IMAP4.abort("IDLE 空响应")
            if resp.startswith(b"+"):
                break
            upper = resp.upper()
            if b"BYE" in upper:
                raise imaplib.IMAP4.abort("服务器 BYE")
            if resp.decode("ascii", "ignore").startswith(tag):
                self.account.idle_supported = False   # 服务器 tagged 拒绝 IDLE
                return False
        else:
            if self._stop.is_set():
                return False   # 停止/暂停打断：不改 idle_supported（可复用账户对象）
            self.account.idle_supported = False
            return False

        got_exists = False
        deadline = time.monotonic() + timeout
        while not self._stop.is_set() and not self._wake.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break                    # 保活周期到 -> DONE 后重发 IDLE
            r, _, _ = select.select([conn.sock], [], [], min(_SELECT_SLICE, remaining))
            if not r:
                continue                 # 分片超时，继续检查 stop/wake
            line = conn.readline()
            if not line:
                raise imaplib.IMAP4.abort("IDLE 空响应")
            if b"BYE" in line.upper():
                raise imaplib.IMAP4.abort("服务器 BYE")
            if _EXISTS_RE.search(line):
                got_exists = True
                break
        # DONE 交互（stop 已关 socket 时这里的 read 会立即抛错退出）
        try:
            conn.send(b"DONE\r\n")
            # 读掉 tagged 结束响应，防止缓冲区残留
            end = time.monotonic() + 5
            while time.monotonic() < end and not self._stop.is_set():
                line = conn.readline()
                if not line:
                    raise imaplib.IMAP4.abort("IDLE DONE 后连接断开")
                upper = line.upper()
                if line.decode("ascii", "ignore").startswith(tag):
                    if b"BAD" in upper or b"NO" in upper:
                        raise imaplib.IMAP4.abort(f"IDLE DONE 被拒绝: {line!r}")
                    break
                if b"BYE" in upper:
                    raise imaplib.IMAP4.abort("服务器 BYE")
        except (imaplib.IMAP4.abort, imaplib.IMAP4.error):
            raise
        except Exception:
            raise imaplib.IMAP4.abort("IDLE DONE 交互失败")
        return got_exists

    # ---------- 轮询模式 ----------
    def _poll_loop(self, conn):
        interval = self.account.poll_interval
        while not self._stop.is_set():
            self._fetch_new(conn)
            # 睡满一个周期，或被 wake/stop 提前唤醒
            woken = self._wake.wait(interval)
            self._wake.clear()
            if self._stop.is_set():
                break
            if woken:
                self._status("手动收信")
            if conn.state == "LOGOUT":
                raise imaplib.IMAP4.abort("服务器已关闭连接")
            conn.select(self._folder_wire(), readonly=True)  # 轮询前刷新连接状态

    # ---------- 收信 ----------
    def _fetch_new(self, conn):
        """抓取服务器上未读（UNSEEN）邮件，经解析去重后入库回调。

        增量下载：UNSEEN 在 readonly 下永不清零，若不加过滤，每个 IDLE
        周期都会把全部未读邮件原文重新下载一遍。这里按 (uidvalidity,
        max_uid) 只对超过已抓取最大 UID 的邮件做 FETCH——SEARCH 很便宜
        （服务端执行），昂贵的原文下载只发生在新邮件上。
        """
        if conn.state != "SELECTED":
            raise imaplib.IMAP4.abort(f"收信前连接状态异常(state={conn.state})")
        folder = self._folder()
        typ, data = conn.uid("search", None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            return
        uids = data[0].split()

        # SELECT 后 imaplib 会把 UIDVALIDITY 存进 untagged_responses
        uv_vals = conn.untagged_responses.get("UIDVALIDITY") or []
        try:
            uidvalidity = int(uv_vals[-1]) if uv_vals else 0
        except (TypeError, ValueError):
            uidvalidity = 0
        old_uv, max_uid = database.get_folder_state(self.account.id, folder)
        if old_uv and uidvalidity and old_uv != uidvalidity:
            # UID 复用：清掉本地缓存重新对账，防止新旧邮件错配
            database.delete_account_mails(self.account.id)
            max_uid = 0
        elif uidvalidity:
            database.set_folder_state(self.account.id, folder,
                                      uidvalidity, max_uid)

        batch = []
        fetched_max = 0
        for uid in uids:
            if self._stop.is_set():
                break
            uid_num = int(uid)
            if uid_num <= max_uid:
                continue            # 本地已有该 UID 的缓存，跳过原文下载
            typ, msgdata = conn.uid("fetch", uid, "(BODY.PEEK[])")
            if (typ != "OK" or not msgdata or not msgdata[0]
                    or not isinstance(msgdata[0], tuple)):
                # 本封抓取失败：水位只推进到已成功的部分。首次失败断批
                # （下轮重试），连续失败则跳过——防一封坏邮件永久挡住其后新邮件
                if uid.decode() in self._failed_uids:
                    continue
                self._failed_uids.add(uid.decode())
                break
            raw = msgdata[0][1]
            parsed = parse_raw(raw)
            parsed_uid = uid.decode()
            fetched_max = max(fetched_max, uid_num)
            batch.append({
                "uid": parsed_uid,
                "message_id": parsed.message_id,
                "subject": parsed.subject or "(无主题)",
                "from_addr": parsed.from_addr,
                "from_name": parsed.from_name,
                "received_at": parsed.received_at,
                "body_text": parsed.body_text,
                "body_html": parsed.body_html,
                "attachment_names": parsed.attachment_names,
            })
        if not batch:
            return
        # 同步入库（DB 有全局锁，线程安全），确认落库后才推进水位——
        # 若先推水位后入库，退出/崩溃窗口内的事件会因 UID ≤ 水位被永久跳过
        new = database.insert_mails(self.account.id, batch, folder=folder)
        if fetched_max and uidvalidity:
            database.set_folder_state(self.account.id, folder,
                                      uidvalidity, fetched_max)
        if new:
            self._on_new_mail(self.account, new)   # 只通知真正新入库的

    def _status(self, text: str):
        try:
            self._on_status(self.account, text)
        except Exception:
            pass

    # ---------- 文件夹列表（供账户对话框调用） ----------
    @staticmethod
    def list_folders(account, password: str) -> list[str]:
        """临时连接服务器，LIST 出全部可选文件夹名（跳过 \\Noselect）。

        供「获取文件夹列表」按钮使用；任何失败都以异常抛出，由调用方提示。
        """
        if account.ssl:
            conn = imaplib.IMAP4_SSL(account.imap_host, account.imap_port,
                                     timeout=_CONNECT_TIMEOUT)
        else:
            conn = imaplib.IMAP4(account.imap_host, account.imap_port,
                                 timeout=_CONNECT_TIMEOUT)
        try:
            imap_login(conn, account, password)
            MailClient._send_client_id(conn)
            typ, data = conn.list('""', '*')
            if typ != "OK" or not data:
                return ["INBOX"]
            folders: list[str] = []
            for item in data:
                if not item:
                    continue
                line = item if isinstance(item, bytes) else item.encode("utf-8", "ignore")
                # 行格式：(flags) "delimiter" "name"
                m = re.match(rb'\(([^)]*)\)\s+"?([^"]*)"?\s+(.+)', line.strip())
                if not m:
                    continue
                flags, _delim, raw_name = m.group(1), m.group(2), m.group(3)
                if b"Noselect" in flags:
                    continue
                name = raw_name.strip()
                # 服务器返回的名字常带引号
                if name.startswith(b'"') and name.endswith(b'"') and len(name) >= 2:
                    name = name[1:-1]
                # 支持修改的 UTF-7（IMAP mUTF-7）：& 开头段先转 + 再 base64 解
                text = _decode_mutf7(name.decode("ascii", "ignore"))
                if text:
                    folders.append(text)
            if "INBOX" not in folders:
                folders.insert(0, "INBOX")
            return folders
        finally:
            try:
                conn.logout()
            except Exception:
                pass


    # ---------- 按需取原文（供「保存附件」等离线功能调用） ----------
    @staticmethod
    def mark_seen(account, password: str, folder: str, uids, seen: bool = True,
                  timeout: float = _CONNECT_TIMEOUT) -> None:
        """临时连接服务器，按 UID 批量设置/清除 \\Seen 标志（v1.7.0）。

        必须非 readonly SELECT 才能改标志。uids 为字符串序列，按数值排序后
        拼成 seq-set 一次发送（单封 STORE 由调用方成批，避免每封一连）。
        folder 传用户可见名（内部做线格式转换）。失败抛异常，由调用方重试。
        """
        uids = sorted({str(u) for u in uids if str(u).isdigit()}, key=int)
        if not uids:
            return
        if account.ssl:
            conn = imaplib.IMAP4_SSL(account.imap_host, account.imap_port,
                                     timeout=timeout)
        else:
            conn = imaplib.IMAP4(account.imap_host, account.imap_port,
                                 timeout=timeout)
        try:
            imap_login(conn, account, password)
            MailClient._send_client_id(conn)
            # STORE 要求可写会话：绝不能 readonly
            typ, data = conn.select(folder_to_wire(folder), readonly=False)
            # select() 对不存在的文件夹返回 ('NO', ...) 而不抛异常：
            # 不在这里拦住，后面 STORE 只会报莫名的状态机错误，误导排查
            if typ != "OK":
                raise imaplib.IMAP4.error(
                    f"SELECT {folder} 失败（文件夹可能已改名/删除/无权限）: {data}")
            op = "+FLAGS.SILENT" if seen else "-FLAGS.SILENT"
            seq = ",".join(uids)
            typ, data = conn.uid("store", seq, f"({op} (\\Seen))")
            if typ != "OK":
                raise imaplib.IMAP4.error(
                    f"STORE \\Seen 失败（folder={folder} uids={seq}）")
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    @staticmethod
    def fetch_raw(account, password: str, folder: str, uid: str,
                  timeout: float = _CONNECT_TIMEOUT) -> bytes:
        """临时连接服务器，按 UID 取回邮件原文（BODY.PEEK[]，不打已读标记）。

        folder 传用户可见名（内部自动做线格式转换）。失败抛异常，由调用方提示。
        """
        if account.ssl:
            conn = imaplib.IMAP4_SSL(account.imap_host, account.imap_port,
                                     timeout=timeout)
        else:
            conn = imaplib.IMAP4(account.imap_host, account.imap_port,
                                 timeout=timeout)
        try:
            imap_login(conn, account, password)
            MailClient._send_client_id(conn)
            conn.select(folder_to_wire(folder), readonly=True)
            typ, msgdata = conn.uid("fetch", uid, "(BODY.PEEK[])")
            if typ != "OK" or not msgdata or not msgdata[0] \
                    or not isinstance(msgdata[0], tuple):
                raise imaplib.IMAP4.error(f"取邮件原文失败（uid={uid}）")
            return msgdata[0][1]
        finally:
            try:
                conn.logout()
            except Exception:
                pass


def folder_to_wire(name: str) -> str:
    """IMAP 协议层的文件夹名：带引号 + 修改版 UTF-7 编码。

    imaplib 以 ascii 编码命令且不加引号：中文名会 UnicodeEncodeError，
    含空格的名字会被拆成多个 atom 被服务器拒绝——统一转码并加引号。
    注意：纯 ASCII 的 `&` 也必须转义为 `&-`（mUTF-7 规范），因此
    含 `&` 的 ASCII 名同样走编码，不做"原始名直通"猜测。
    """
    try:
        name.encode("ascii")
        if "&" not in name:
            return f'"{name}"'
    except UnicodeEncodeError:
        pass
    return f'"{_encode_mutf7(name)}"'


def _decode_mutf7(name: str) -> str:
    """IMAP 修改版 UTF-7 解码（RFC 3501 5.1.3）。纯 ASCII 原样返回；解码失败返回原文。"""
    if "&" not in name:
        return name
    try:
        out, i = [], 0
        while i < len(name):
            ch = name[i]
            if ch != "&":
                out.append(ch)
                i += 1
                continue
            j = name.find("-", i)
            if j < 0:
                out.append(name[i:])
                break
            b64 = name[i + 1:j]
            if not b64:
                out.append("&")
            else:
                b64 = b64.replace(",", "/")
                pad = "=" * (-len(b64) % 4)
                out.append(base64.b64decode(b64 + pad).decode("utf-16-be"))
            i = j + 1
        return "".join(out)
    except Exception:
        return name


def _encode_mutf7(text: str) -> str:
    """IMAP 修改版 UTF-7 编码（_decode_mutf7 的逆运算）。

    ASCII 直通（& 转义为 &-）；非 ASCII 段整体 base64（UTF-16BE），
    base64 的 "/" 按惯例写成 ","。
    """
    out: list[str] = []
    buf: list[str] = []

    def flush():
        if buf:
            b64 = base64.b64encode("".join(buf).encode("utf-16-be")).decode("ascii")
            out.append("&" + b64.rstrip("=").replace("/", ",") + "-")
            buf.clear()

    for ch in text:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)
