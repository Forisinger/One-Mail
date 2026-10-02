# -*- coding: utf-8 -*-
"""极简 HTML → tkinter Text 富文本渲染器（v1.9.0，修复收件富文本显示）。

设计要点：
- 纯标准库 html.parser，零第三方依赖；不加载任何远程资源（img 忽略，
  script/style 内容丢弃）——tkinter Text 渲染本身无脚本执行能力，安全。
- 支持：b/strong/i/em/u/s、span 颜色（内联 style="color:..."）、font color、
  h1-h6、br/p/div/tr/li 列表、a（链接文字着色+下划线）、blockquote、pre。
- 宽容解析：未闭合标签按栈恢复，坏 HTML 不抛异常、最坏退化为纯文本。
- 只往 Text 控件插入文本与标签，内存开销与正文同量级。
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

import tkinter as tk

from .imgload import MAX_IMAGES   # 占位登记上限与后台加载共用一份定义

# 产生换行的块级标签
_BLOCK = {"p", "div", "tr", "table", "ul", "ol", "blockquote", "section",
          "h1", "h2", "h3", "h4", "h5", "h6", "li", "pre"}
_SKIP = {"script", "style", "head", "title"}
_HEADING = {"h1": 4, "h2": 3, "h3": 2, "h4": 1, "h5": 1, "h6": 1}
_COLOR_RE = re.compile(r"(?i)(?:^|;)\s*color\s*:\s*([#\w]+)")
_LIST_PREFIX = {  # 列表项前缀由 li 开始时决定
    "ul": "• ", "ol": "", "": "• "}
# CJK 字符（空白折叠时两侧均为 CJK 则不加空格，v1.10.1）
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\u3000-\u303f\uff01-\uff5e]")


class _Style:
    __slots__ = ("bold", "italic", "underline", "strike", "color", "link", "size")

    def __init__(self, **kw):
        self.bold = kw.get("bold", False)
        self.italic = kw.get("italic", False)
        self.underline = kw.get("underline", False)
        self.strike = kw.get("strike", False)
        self.color = kw.get("color", "")
        self.link = kw.get("link", False)
        self.size = kw.get("size", 0)   # 相对基准字号 ±

    def copy(self, **kw):
        s = _Style(bold=self.bold, italic=self.italic, underline=self.underline,
                   strike=self.strike, color=self.color, link=self.link,
                   size=self.size)
        for k, v in kw.items():
            setattr(s, k, v)
        return s


class _Renderer(HTMLParser):
    def __init__(self, widget: tk.Text, base_font, colors: dict[str, str]):
        super().__init__(convert_charrefs=True)
        self.w = widget
        self.base_font = base_font
        self.c = colors
        self.style = _Style()
        self.stack: list[tuple[str, _Style]] = []
        self.skip: list[str] = []
        self._tag_no = 0
        self._list_stack: list[str] = []
        self._ol_counters: list[int] = []   # 与 _list_stack 对齐，ol 序号计数
        # v1.10.0：img 占位登记 [(标签名, src)]，图片由 imgload 后台加载回填
        self.images: list[tuple[str, str]] = []
        self.w.tag_configure("imgph", foreground=colors.get("GRAY", "#888888"))

    # ---------- 标签管理 ----------
    def _tag(self, **conf) -> str:
        self._tag_no += 1
        name = f"ht{self._tag_no}"
        self.w.tag_configure(name, **conf)
        return name

    def _tags_for(self, s: _Style) -> tuple:
        tags = []
        if s.bold:
            tags.append(self._tag(font=self.base_font + ("bold",)))
        if s.italic:
            tags.append(self._tag(font=self.base_font + ("italic",)))
        if s.underline or s.link:
            tags.append(self._tag(underline=1))
        if s.strike:
            tags.append(self._tag(overstrike=1))
        if s.size:
            fam, sz, *rest = self.base_font
            f = [fam, max(8, sz + s.size)] + rest
            if s.bold:
                f.append("bold")
            tags.append(self._tag(font=tuple(f)))
        if s.link:
            tags.append(self._tag(foreground=self.c["ACCENT"]))
        elif s.color:
            tags.append(self._tag(foreground=s.color))
        return tuple(tags)

    # ---------- 解析事件 ----------
    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip.append(tag)
            return
        if self.skip:
            return
        if tag == "br":
            self.w.insert("end", "\n")
            return
        if tag in _BLOCK:
            self.w.insert("end", "\n")
        if tag in ("ul", "ol"):
            self._list_stack.append(tag)
            self._ol_counters.append(0 if tag == "ol" else -1)
        elif tag == "li" and self._list_stack:
            kind = self._list_stack[-1]
            if kind == "ol":
                self._ol_counters[-1] += 1
                self.w.insert("end", f"{self._ol_counters[-1]}. ",
                              self._tags_for(self.style))
            else:
                self.w.insert("end", _LIST_PREFIX.get(kind, "• "))

        old = self.style
        a = dict(attrs)
        if tag == "img":
            self._handle_img(a)
            return
        if tag in ("b", "strong"):
            self.style = old.copy(bold=True)
        elif tag in ("i", "em"):
            self.style = old.copy(italic=True)
        elif tag == "u":
            self.style = old.copy(underline=True)
        elif tag == "s" or tag == "strike":
            self.style = old.copy(strike=True)
        elif tag == "a":
            self.style = old.copy(link=True)
        elif tag in _HEADING:
            self.style = old.copy(bold=True, size=_HEADING[tag])
        elif tag in ("span", "font"):
            color = ""
            if tag == "font":
                color = a.get("color", "") or ""
            m = _COLOR_RE.search(a.get("style", "") or "")
            if m:
                color = m.group(1)
            if color.startswith("#") and len(color) in (4, 7):
                self.style = old.copy(color=color)
        self.stack.append((tag, old))

    def handle_endtag(self, tag):
        if tag in _SKIP:
            if tag in self.skip:
                # 逐层弹出直到匹配：容忍跳过区内嵌套
                while self.skip:
                    if self.skip.pop() == tag:
                        break
            return
        if self.skip:
            return
        if tag in ("ul", "ol") and self._list_stack:
            self._list_stack.pop()
            if self._ol_counters:
                self._ol_counters.pop()
        # 栈式恢复：找到最近的同名开始标签，弹到它为止（未闭合标签自动收敛）
        for k in range(len(self.stack) - 1, -1, -1):
            if self.stack[k][0] == tag:
                self.style = self.stack[k][1]
                del self.stack[k:]
                break

    def handle_data(self, data):
        if self.skip:
            return
        if self.stack and self.stack[-1][0] == "pre":
            text = data
        else:
            # 空白折叠：CJK 两侧的换行直接去掉不加空格（中文邮件源码常折行，
            # 折叠成空格会凭空多出空格，v1.10.1）
            def _fold(m):
                prev = data[m.start() - 1] if m.start() > 0 else ""
                nxt = data[m.end()] if m.end() < len(data) else ""
                if _CJK_RE.match(prev) and _CJK_RE.match(nxt):
                    return ""
                return " "
            text = re.sub(r"\s+", _fold, data)
            if not text.strip():
                return  # 纯空白（缩进/换行）不插入，排版由块级标签负责
        self.w.insert("end", text, self._tags_for(self.style))

    # ---------- 图片（v1.10.0）：插占位符并登记，交给 imgload 异步回填 ----------
    def _handle_img(self, attrs: dict):
        src = (attrs.get("src") or "").strip()
        if not src:
            return
        if len(self.images) >= MAX_IMAGES:   # 与后台加载上限同源
            return
        name = f"img{self._tag_no}"
        self._tag_no += 1
        self.w.tag_configure(name)
        alt = (attrs.get("alt") or "").strip()
        self.w.insert("end", alt or "［图片］", (name, "imgph"))
        self.images.append((name, src))

    def handle_startendtag(self, tag, attrs):
        # 自闭合写法 <img/> <br/>：img 需要单独路径，br 需要换行
        if tag in _SKIP:
            return
        if self.skip:
            return
        if tag == "br":
            self.w.insert("end", "\n")
        elif tag == "img":
            self._handle_img(dict(attrs))

    def handle_decl(self, decl):
        pass


def render_html(widget: tk.Text, html: str, base_font, colors: dict[str, str]) -> list:
    """把 HTML 正文渲染进 Text 控件（调用方保证控件已 state="normal"）。

    返回 [(占位标签名, src)] 供异步图片加载（v1.10.0）；
    任何解析异常都被吞掉：最坏情况正文缺失，但绝不让收件流程报错。
    """
    if not html:
        return []
    try:
        r = _Renderer(widget, base_font, colors)
        r.feed(html)
        r.close()
        return r.images
    except Exception:
        return []
