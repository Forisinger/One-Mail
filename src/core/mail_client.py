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
import socket
import threading
import time
import traceback

from .parser import parse_raw

_IMAP4_PORT_SSL = 993
_IDLE_REFRESH = 24 * 60          # IDLE 保活周期（秒）
_RECONNECT_BASE = 5              # 重连退避起点（秒）
_RECONNECT_MAX = 10 * 60

# 从 IDLE 未请求响应里抓邮箱状态行（如 * 23 EXISTS）
_EXISTS_RE = re.compile(rb"\*\s+(\d+)\s+EXISTS", re.IGNORECASE)

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
        self._thread: threading.Thread | None = None
        self._last_seen_exists = 0   # IDLE 收信的基准邮箱总数

    # ---------- 生命周期 ----------
    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name=f"mail-{self.account.email}", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()

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
                self._status("已连接")
                backoff = _RECONNECT_BASE
                if self._probe_idle(conn):
                    self._idle_loop(conn)
                else:
                    self._status("服务器不支持 IDLE，转为轮询")
                    self._poll_loop(conn)
            except (imaplib.IMAP4.error, socket.error, OSError) as e:
                self._status(f"连接异常：{type(e).__name__}: {e}，{backoff}s 后重连")
            except Exception:  # 未知异常也绝不退出线程
                self._status("未知错误，稍后重连")
                traceback.print_exc()
            finally:
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
            conn = imaplib.IMAP4_SSL(acc.imap_host, acc.imap_port)
        else:
            conn = imaplib.IMAP4(acc.imap_host, acc.imap_port)
        conn.login(acc.email, self.password)
        self._send_client_id(conn)      # 163/126：必须上报客户端 ID
        conn.select(self._folder(), readonly=True)
        return conn

    def _folder(self) -> str:
        """收信文件夹名（空值回退 INBOX）。"""
        return (getattr(self.account, "folder", "") or "INBOX").strip() or "INBOX"

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
        typ, data = conn.select(self._folder(), readonly=True)
        if typ != "OK":
            raise imaplib.IMAP4.error(f"SELECT {self._folder()} failed")
        self._last_seen_exists = int(data[0] or b"0")
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
            self._fetch_new(conn)

    def _idle_wait(self, conn, timeout: float) -> bool:
        """进入 IDLE 等待。返回 True 表示服务器推送了 EXISTS（可能有新邮件）。"""
        tag = conn._new_tag().decode()
        conn.send(f"{tag} IDLE\r\n".encode())
        resp = conn.readline()
        # 服务器接受 IDLE 的标志是发送继续行（+ ...），各家文案不同
        if not resp.startswith(b"+"):
            self.account.idle_supported = False
            return False

        got_exists = False
        conn.sock.settimeout(timeout)
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline and not self._stop.is_set():
                line = conn.readline()          # 阻塞直到有推送/超时
                if not line:
                    raise imaplib.IMAP4.abort("IDLE 空响应")
                if b"BYE" in line.upper():
                    raise imaplib.IMAP4.abort("服务器 BYE")
                if _EXISTS_RE.search(line):
                    got_exists = True
                    break
        except socket.timeout:
            pass                                 # 正常超时 -> 重发 IDLE
        finally:
            conn.sock.settimeout(None)
            try:
                conn.send(b"DONE\r\n")
                # 读掉 tagged 结束响应，防止缓冲区残留
                end = time.monotonic() + 5
                while time.monotonic() < end:
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
            if self._stop.wait(interval):
                break
            if conn.state == "LOGOUT":
                raise imaplib.IMAP4.abort("服务器已关闭连接")
            conn.select(self._folder(), readonly=True)  # 轮询前刷新连接状态

    # ---------- 收信 ----------
    def _fetch_new(self, conn):
        """抓取服务器上未读（UNSEEN）邮件，经解析去重后入库回调。"""
        if conn.state != "SELECTED":
            raise imaplib.IMAP4.abort(f"收信前连接状态异常(state={conn.state})")
        typ, data = conn.uid("search", None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            return
        uids = data[0].split()
        batch = []
        for uid in uids:
            if self._stop.is_set():
                break
            typ, msgdata = conn.uid("fetch", uid, "(BODY.PEEK[])")
            if typ != "OK" or not msgdata or not msgdata[0]:
                continue
            raw = msgdata[0][1]
            parsed = parse_raw(raw)
            parsed_uid = uid.decode()
            batch.append({
                "uid": parsed_uid,
                "message_id": parsed.message_id,
                "subject": parsed.subject or "(无主题)",
                "from_addr": parsed.from_addr,
                "from_name": parsed.from_name,
                "received_at": parsed.received_at,
                "body_text": parsed.body_text,
                "attachment_names": parsed.attachment_names,
            })
        if batch:
            self._on_new_mail(self.account, batch)

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
            conn = imaplib.IMAP4_SSL(account.imap_host, account.imap_port)
        else:
            conn = imaplib.IMAP4(account.imap_host, account.imap_port)
        try:
            conn.login(account.email, password)
            _send_client_id(conn)
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
