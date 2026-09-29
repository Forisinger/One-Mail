# -*- coding: utf-8 -*-
"""Text 控件富文本标签 → HTML 导出。

逐字符扫描 tkinter Text 的标签状态，输出 <b>/<i>/<u>/<span style> 标记，
普通字符做 HTML 转义，换行转 <br>。万字符级正文耗时可忽略。

标签命名约定（与 compose_window 保持一致）：
- 字体组合标签：fb{0,1}i{0,1}u{0,1}，如 fb1i0u1 = 加粗
- 颜色标签：color-#rrggbb
"""
from __future__ import annotations

import html as html_mod

import tkinter as tk

COLOR_PREFIX = "color-"


def font_tag_name(bold: bool, italic: bool, underline: bool) -> str:
    return f"fb{int(bold)}i{int(italic)}u{int(underline)}"


def char_flags(widget: tk.Text, index: str) -> tuple[bool, bool, bool, str | None]:
    """取某字符处的样式状态 (bold, italic, underline, color)。"""
    bold = italic = underline = False
    color = None
    for n in widget.tag_names(index):
        if n.startswith("fb") and len(n) == 7:
            bold, italic, underline = n[2] == "1", n[4] == "1", n[6] == "1"
        elif n.startswith(COLOR_PREFIX):
            color = n[len(COLOR_PREFIX):]
    return bold, italic, underline, color


def _open_spans(b: bool, i: bool, u: bool, color: str | None) -> str:
    parts = []
    if b:
        parts.append("<b>")
    if i:
        parts.append("<i>")
    if u:
        parts.append("<u>")
    if color:
        parts.append(f'<span style="color:{color}">')
    return "".join(parts)


def _close_spans(b: bool, i: bool, u: bool, color: str | None) -> str:
    parts = []
    if color:
        parts.append("</span>")
    if u:
        parts.append("</u>")
    if i:
        parts.append("</i>")
    if b:
        parts.append("</b>")
    return "".join(parts)


def text_to_html(widget: tk.Text) -> str:
    """将 Text 控件内容（含样式标签）导出为 HTML 片段。

    字符一律从 Tcl 侧取（widget.get(idx)）而不是迭代 Python 字符串：
    Tcl 索引按 UTF-16 代码单元推进，emoji 等星形平面字符占 2 个单位，
    用 Python 码点迭代会导致其后所有字符的样式索引错位。
    """
    out: list[str] = []
    prev = (False, False, False, None)
    has_style = False
    text = widget.get("1.0", "end-1c")
    idx = "1.0"
    while widget.compare(idx, "<", "end-1c"):
        ch = widget.get(idx)
        b, i, u, color = char_flags(widget, idx)
        cur = (b, i, u, color)
        if cur != prev:
            has_style = has_style or any(cur)
            out.append(_close_spans(*prev))
            out.append(_open_spans(*cur))
            prev = cur
        if ch == "\n":
            out.append(_close_spans(*prev))
            out.append("<br>\n")
            prev = (False, False, False, None)
        else:
            out.append(html_mod.escape(ch, quote=False))
        idx = widget.index(f"{idx} +1c")
    out.append(_close_spans(*prev))
    if not has_style:
        # 无任何样式：退化为纯 <br> 版本
        return html_mod.escape(text, quote=False).replace("\n", "<br>\n")
    return "".join(out)
