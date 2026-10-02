# -*- coding: utf-8 -*-
"""主题调色板（v1.9.0）：集中管理全部 UI 配色，支持浅色/深色两套。

切换主题在设置对话框完成，保存到 config.settings.theme 后**重启生效**
（tkinter 控件颜色在构造时写入，运行时全量重绘的复杂度远超收益）。
"""
from __future__ import annotations

from storage import config as config_store

THEMES: dict[str, dict[str, str]] = {
    "light": {
        "BG": "#eef1f6",          # 窗口底
        "CARD": "#ffffff",        # 卡片
        "TEXT": "#1f2937",
        "GRAY": "#6b7280",
        "ACCENT": "#1e64dc",      # 主蓝
        "ACCENT_DARK": "#173f8f", # 未读文字
        "ACCENT_SOFT": "#e3ecfb", # 选中底色
        "ERR": "#cc3333",        # 异常账户/错误提示
        "ROW_ALT": "#f4f7fc",     # 隔行底色
        "DIVIDER": "#e2e8f2",
        "HEADING": "#e8edf6",     # 表头底色
        "BORDER": "#d4dcea",
        "SEL_FG": "#ffffff",
    },
    "dark": {
        "BG": "#1b1e24",
        "CARD": "#23272f",
        "TEXT": "#e5e7eb",
        "GRAY": "#9ca3af",
        "ACCENT": "#4d8dff",
        "ACCENT_DARK": "#a8c7ff",  # 深底下未读文字要亮
        "ACCENT_SOFT": "#2c3a55",
        "ERR": "#ff7b72",        # 异常账户/错误提示（深色版）
        "ROW_ALT": "#272c35",
        "DIVIDER": "#3a4150",
        "HEADING": "#2d333d",
        "BORDER": "#3a4150",
        "SEL_FG": "#ffffff",
    },
}

DEFAULT_THEME = "light"


def current_theme() -> str:
    try:
        t = config_store.load().get("settings", {}).get("theme", DEFAULT_THEME)
    except Exception:
        t = DEFAULT_THEME
    return t if t in THEMES else DEFAULT_THEME


def colors() -> dict[str, str]:
    """当前主题的调色板（每次调用现读配置，窗口构造时取一次即可）。"""
    return THEMES[current_theme()]
