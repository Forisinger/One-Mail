# -*- coding: utf-8 -*-
"""SMTP 发信引擎：组装 MIME、发送、尽力同步"已发送"文件夹。

设计要点：
- 纯标准库（smtplib + email），与收信引擎一样零第三方依赖
- build_mime / send_mail 分离：MIME 组装可离线单测
- save_to_sent 为 best-effort：任何失败静默降级，不影响发信结果
"""
from __future__ import annotations

import imaplib
import mimetypes
import os
import smtplib
from email.header import Header
from email.message import Message
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from .account import Account

# 已发送文件夹的常见命名（按顺序探测）
SENT_FOLDER_CANDIDATES = ("已发送", "Sent Messages", "Sent", "Sent Items")


def build_mime(account: Account, to_addrs: list[str], subject: str,
               body: str, attachments: list[str] | None = None) -> Message:
    """组装 MIME 消息（UTF-8 纯文本 + 附件）。不联网，可离线单测。"""
    msg = MIMEMultipart()
    msg["From"] = formataddr((str(Header(account.name or account.email, "utf-8")),
                              account.email))
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = Header(subject or "(无主题)", "utf-8")
    msg.attach(MIMEText(body or "", "plain", "utf-8"))

    for path in attachments or []:
        ctype, _ = mimetypes.guess_type(path)
        if not ctype:
            ctype = "application/octet-stream"
        subtype = ctype.split("/", 1)[1]
        with open(path, "rb") as f:
            data = f.read()
        # 统一走二进制附件类型，文本/图片照样能用，最稳妥
        part = MIMEApplication(data, _subtype=subtype)
        # 中文/特殊字符文件名：add_header 传 3 元组即自动做 RFC 2231 编码
        filename = os.path.basename(path)
        if filename.isascii():
            part.add_header("Content-Disposition", "attachment", filename=filename)
        else:
            part.add_header("Content-Disposition", "attachment",
                            filename=("utf-8", "", filename))
        msg.attach(part)
    return msg


def send_mail(account: Account, password: str, to_addrs: list[str],
              subject: str, body: str,
              attachments: list[str] | None = None,
              timeout: float = 30) -> Message:
    """登录 SMTP 并发送。成功返回已组装的消息；失败抛 smtplib.SMTPException 等异常。"""
    msg = build_mime(account, to_addrs, subject, body, attachments)
    host, port = account.smtp_endpoint()
    with smtplib.SMTP_SSL(host, port, timeout=timeout) as srv:
        srv.login(account.email, password)
        srv.send_message(msg)
    return msg


def save_to_sent(account: Account, password: str, msg: Message,
                 timeout: float = 20) -> bool:
    """尽力把已发邮件 APPEND 到服务器"已发送"文件夹。返回是否成功。

    独立短连接，用完即关；探测不到已发送文件夹或任何异常都静默降级
    （163 等多数服务商在网页端会自行显示已发邮件）。
    """
    try:
        if account.ssl:
            conn = imaplib.IMAP4_SSL(account.imap_host, account.imap_port, timeout=timeout)
        else:
            conn = imaplib.IMAP4(account.imap_host, account.imap_port, timeout=timeout)
        try:
            conn.login(account.email, password)
            folder = None
            for cand in SENT_FOLDER_CANDIDATES:
                typ, boxes = conn.list()
                if typ != "OK":
                    break
                for raw in boxes or []:
                    try:
                        name = raw.decode("utf-8", "ignore").rsplit("/", 1)[-1]
                        name = name.strip().strip('"').split("/")[-1].strip('"')
                        if name == cand or raw.decode("utf-8", "ignore").find(cand) >= 0:
                            folder = cand
                            break
                    except Exception:
                        continue
                if folder:
                    break
            if not folder:
                return False
            typ, _ = conn.append(folder, r"(\Seen)", None, msg.as_bytes())
            return typ == "OK"
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except Exception:
        return False
