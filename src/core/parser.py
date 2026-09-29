# -*- coding: utf-8 -*-
"""邮件解析：MIME 解析、正文提取、来源头解码。

设计要点：
- 只用标准库 email，无第三方依赖
- 编码兜底链：utf-8 -> gbk -> gb2312 -> latin-1（国内邮箱大量 GBK）
- HTML 正文剥标签转纯文本，不引入 BeautifulSoup
- 解析失败保底返回空值，绝不抛异常打断收信流程
"""
from __future__ import annotations

import email
import re
from dataclasses import dataclass, field
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

_CHARSET_FALLBACKS = ("utf-8", "gbk", "gb2312", "big5", "latin-1")
_MAX_BODY = 64 * 1024  # 正文入库上限 64KB


@dataclass
class ParsedMail:
    """解析后的邮件。任何字段解析失败都置空，不抛异常。"""
    message_id: str = ""
    subject: str = ""
    from_addr: str = ""
    from_name: str = ""
    received_at: str = ""          # ISO 格式，解析失败为空
    body_text: str = ""
    attachment_names: list = field(default_factory=list)


class _HTML2Text(HTMLParser):
    """极简 HTML -> 纯文本转换器。

    skip 标签按「进入时记住标签名」处理而非纯计数：真实邮件常有不闭合的
    <script>/<style>（营销邮件、被转发截断的邮件）。跳过区内一旦出现
    真实排版标记（<body>/<div>/<p> 等），即认定标签未闭合并从该处恢复
    解析，避免整封正文被吞。
    """
    _SKIP = {"script", "style", "head", "title"}
    _MAX_SKIP_DATA = 256 * 1024   # 跳过区内数据超限视为未闭合，强制恢复
    # script/style 源码里偶见 "<p>" 之类字符串；这里宁可多恢复也不吞正文
    _RESUME_RE = re.compile(
        r"<\s*/?\s*(body|div|p|br|table|tr|td|th|h[1-6]|font|span|a)\b", re.I)

    _MAX_SKIP_DEPTH = 8           # 恢复解析的嵌套深度上限，防递归爆栈

    def __init__(self, depth: int = 0):
        super().__init__(convert_charrefs=True)
        self._depth = depth
        self._chunks: list[str] = []
        self._skip_stack: list[str] = []
        self._skip_bytes = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_stack.append(tag)
            self._skip_bytes = 0
        elif tag in ("br", "p", "div", "tr", "li") and not self._skip_stack:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if self._skip_stack:
            if tag == self._skip_stack[-1]:
                self._skip_stack.pop()
                self._skip_bytes = 0
            return
        if tag in ("p", "div", "tr"):
            self._chunks.append("\n")

    def handle_data(self, data):
        if not self._skip_stack:
            if data.strip():
                self._chunks.append(data)
            return
        self._skip_bytes += len(data)
        if self._skip_bytes > self._MAX_SKIP_DATA:
            self._skip_stack.clear()   # 超限兜底恢复
            return
        m = self._RESUME_RE.search(data)
        if not m:
            return
        if self._depth >= self._MAX_SKIP_DEPTH:
            return   # 深度超限：丢弃该段，不再递归恢复
        # 未闭合的 script/style：从第一处真实标记恢复，用子解析器处理剩余部分
        self._skip_stack.clear()
        sub = _HTML2Text(depth=self._depth + 1)
        sub.feed(data[m.start():])
        text = sub.text()
        if text:
            self._chunks.append(text)

    def text(self) -> str:
        # CDATA 模式（script/style）下未闭合的标签会让剩余输入永远停在
        # 缓冲区、不产生任何事件——在这里取回缓冲内容做恢复解析
        if self._skip_stack and self.rawdata:
            raw = self.rawdata
            self.rawdata = ""
            self._skip_stack.clear()
            m = self._RESUME_RE.search(raw)
            if m:
                if self._depth < self._MAX_SKIP_DEPTH:
                    sub = _HTML2Text(depth=self._depth + 1)
                    sub.feed(raw[m.start():])
                    sub.close()
                    text = sub.text()
                    if text:
                        self._chunks.append(text)
        raw = "".join(self._chunks)
        return re.sub(r"\n{3,}", "\n\n", raw).strip()


def _decode_payload(part) -> str:
    """按兜底链解码字节负载。"""
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    for cs in (part.get_content_charset(),) + _CHARSET_FALLBACKS:
        if not cs:
            continue
        try:
            return payload.decode(cs, errors="strict")
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", errors="replace")


def _decode_header_value(value: str) -> str:
    """解码 RFC2047 编码头（=?gbk?B?...?= 之类），并处理折叠头。"""
    if not value:
        return ""
    try:
        chunks = []
        for raw, charset in decode_header(value):
            if isinstance(raw, bytes):
                for cs in (charset,) + _CHARSET_FALLBACKS:
                    if not cs:
                        continue
                    try:
                        raw = raw.decode(cs, errors="strict")
                        break
                    except (LookupError, UnicodeDecodeError):
                        continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
            chunks.append(raw)
        return "".join(chunks)
    except Exception:
        return value or ""


def _extract_body(msg) -> tuple[str, list[str]]:
    """遍历 MIME 树，取正文（plain 优先）与附件名列表。"""
    body_plain = ""
    body_html = ""
    attachments: list[str] = []

    for part in msg.walk():
        ctype = part.get_content_type()
        disp = str(part.get("Content-Disposition", "") or "")
        filename = part.get_filename()

        if filename:
            attachments.append(_decode_header_value(filename))
            continue
        if disp and "attachment" in disp.lower():
            attachments.append(_decode_header_value(filename or "(未命名附件)"))
            continue
        if part.is_multipart():
            continue
        if ctype == "text/plain" and not body_plain:
            body_plain = _decode_payload(part)
        elif ctype == "text/html" and not body_html:
            body_html = _decode_payload(part)

    if body_plain.strip():
        text = body_plain
    else:
        try:
            text = _HTML2Text()
            text.feed(body_html)
            text = text.text()
        except Exception:
            text = body_html
    return text.strip()[:_MAX_BODY], attachments


def parse_raw(raw: bytes) -> ParsedMail:
    """解析原始邮件字节流 -> ParsedMail。永不抛异常。"""
    out = ParsedMail()
    try:
        msg = email.message_from_bytes(raw)
    except Exception:
        return out

    try:
        out.message_id = (msg.get("Message-ID") or "").strip()
    except Exception:
        pass

    try:
        out.subject = _decode_header_value(msg.get("Subject", ""))
    except Exception:
        pass

    try:
        name, addr = parseaddr(msg.get("From", ""))
        out.from_addr = addr
        out.from_name = _decode_header_value(name) or addr
    except Exception:
        pass

    try:
        dt = parsedate_to_datetime(msg.get("Date"))
        out.received_at = dt.isoformat(sep=" ", timespec="seconds")
    except Exception:
        pass

    try:
        out.body_text, out.attachment_names = _extract_body(msg)
    except Exception:
        pass
    return out


def extract_attachments(raw: bytes) -> list[tuple[str, bytes]]:
    """从原始邮件字节提取全部附件，返回 (已解码文件名, 内容字节) 列表。

    供「保存附件」功能按需调用（邮件原文不落盘，需要时按 UID 重新取）。
    解析失败返回空列表，绝不抛异常。
    """
    try:
        msg = email.message_from_bytes(raw)
        out: list[tuple[str, bytes]] = []
        for part in msg.walk():
            filename = part.get_filename()
            if not filename:
                disp = str(part.get("Content-Disposition", "") or "")
                if not (disp and "attachment" in disp.lower()):
                    continue
                filename = "(未命名附件)"
            if part.defects:
                continue   # 编码声明与实际不符（如损坏 base64）：宁缺毋滥
            if part.get_content_maintype() == "message":
                # message/rfc822（.eml）附件：get_payload(decode=True) 返回
                # None，用原始字节作为内容保存
                payload = part.as_bytes()
            else:
                payload = part.get_payload(decode=True)
            if payload is None:
                continue
            out.append((_decode_header_value(filename), payload))
        return out
    except Exception:
        return []
