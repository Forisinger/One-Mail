# -*- coding: utf-8 -*-
"""主题调色板（v1.9.0）：集中管理全部 UI 配色，支持浅色/深色两套。

v1.11.0 起支持**强调色自定义**：`settings.theme_overrides` 可按主题覆盖
`ACCENT`，其余联动色（ACCENT_DARK / ACCENT_SOFT）自动派生，保证未读文字
与选中底色的对比度不因自定义而失效。

切换主题/强调色在设置对话框完成，保存到 config 后**重启生效**（tkinter
控件颜色在构造时写入，运行时全量重绘的复杂度远超收益）。
"""
from __future__ import annotations

import re

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
        # —— 控件面（v1.11.2：ttk 控件显式着色，不再依赖系统原生外观）——
        "FIELD": "#ffffff",      # 输入框/下拉/列表内容底色
        "BTN": "#ffffff",        # 按钮面
        "BTN_ACTIVE": "#e8eefb",  # 悬停
        "BTN_PRESSED": "#d5e0f5",  # 按下
        "TAB": "#dde4f0",        # 未选中页签
        "TROUGH": "#e6eaf2",     # 滚动条槽
        "DISABLED": "#a8aeb8",   # 禁用文字
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
        # —— 控件面（比卡片略亮，形成层次，避免深色主题里出现白色控件）——
        "FIELD": "#2b303a",
        "BTN": "#333a45",
        "BTN_ACTIVE": "#3d4552",
        "BTN_PRESSED": "#2a303a",
        "TAB": "#262b33",
        "TROUGH": "#1f232a",
        "DISABLED": "#6b7280",
    },
}

DEFAULT_THEME = "light"

# 目前唯一开放覆盖的键：ACCENT（其余联动色自动派生，保证对比度）
_OVERRIDE_KEY = "ACCENT"

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


# ---------- 颜色工具（纯函数，可离线单测） ----------

def normalize_hex(value: str) -> str:
    """归一化为 #rrggbb；非法输入（含非字符串）返回空串，由调用方回退默认。"""
    if not isinstance(value, str):
        return ""
    m = _HEX_RE.match(value.strip())
    if not m:
        return ""
    h = m.group(1).lower()
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return "#" + h


def _to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = normalize_hex(hex_color)[1:]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(v))):02x}" for v in rgb)


def mix(color_a: str, color_b: str, ratio: float) -> str:
    """按 ratio（0=全 a，1=全 b）线性混色。任一输入非法则返回 color_a。"""
    try:
        a, b = _to_rgb(color_a), _to_rgb(color_b)
    except (ValueError, IndexError):
        return color_a
    r = max(0.0, min(1.0, float(ratio)))
    return _to_hex(tuple(a[i] + (b[i] - a[i]) * r for i in range(3)))


def derive_palette(theme: str, base: dict[str, str],
                   accent: str) -> dict[str, str]:
    """在默认色板基础上应用强调色覆盖并派生联动色。

    - light：未读文字往黑里压（深蓝字），选中底往白里提（浅蓝底）
    - dark：未读文字往白里提（亮蓝字，深底下才看得清），选中底贴近背景
    """
    c = dict(base)
    acc = normalize_hex(accent)
    if not acc:
        return c
    c["ACCENT"] = acc
    if theme == "dark":
        c["ACCENT_DARK"] = mix(acc, "#ffffff", 0.55)
        c["ACCENT_SOFT"] = mix(acc, base.get("BG", "#1b1e24"), 0.78)
    else:
        c["ACCENT_DARK"] = mix(acc, "#000000", 0.35)
        c["ACCENT_SOFT"] = mix(acc, "#ffffff", 0.88)
    return c


# ---------- 配置读写 ----------

def _settings() -> dict:
    try:
        return config_store.load().get("settings", {}) or {}
    except Exception:
        return {}


def current_theme() -> str:
    t = _settings().get("theme", DEFAULT_THEME)
    return t if t in THEMES else DEFAULT_THEME


def default_accent(theme: str) -> str:
    return THEMES.get(theme, THEMES[DEFAULT_THEME])["ACCENT"]


def accent_override(theme: str) -> str:
    """已保存的强调色覆盖值；无/非法返回空串。"""
    ov = _settings().get("theme_overrides") or {}
    if not isinstance(ov, dict):
        return ""
    item = ov.get(theme) or {}
    if not isinstance(item, dict):
        return ""
    return normalize_hex(item.get(_OVERRIDE_KEY, ""))


def effective_accent(theme: str) -> str:
    """实际生效的强调色（覆盖优先，否则主题默认）。"""
    return accent_override(theme) or default_accent(theme)


def colors() -> dict[str, str]:
    """当前主题的完整调色板（含强调色覆盖），每次调用现读配置。"""
    theme = current_theme()
    base = dict(THEMES[theme])
    acc = accent_override(theme)
    return derive_palette(theme, base, acc) if acc else base


def set_accent(theme: str, accent: str) -> bool:
    """写入强调色覆盖。accent 为空/非法时等价于恢复默认。返回是否已写入。

    只写 ACCENT 一个键，非法值一律当作"恢复默认"，不落脏数据。
    """
    acc = normalize_hex(accent)
    try:
        cfg = config_store.load()
        st = cfg.setdefault("settings", {})
        ov = st.setdefault("theme_overrides", {})
        if not isinstance(ov, dict):
            ov = {}
            st["theme_overrides"] = ov
        if acc:
            ov[theme] = {_OVERRIDE_KEY: acc}
        else:
            ov.pop(theme, None)
            if not ov:
                st.pop("theme_overrides", None)   # 不留空容器
        config_store.save(cfg)
        return bool(acc)
    except Exception:
        return False


# ---------- 窗口级应用（v1.11.2） ----------

def window_colors(win, palette: dict[str, str] | None = None) -> dict[str, str]:
    """把 Toplevel 自身背景也切到主题色，返回所用调色板。

    ttk.Frame 只覆盖内容区，Toplevel 露出的一圈仍是系统色——深色主题下
    表现为窗口边缘发白。这里显式设置；不 import tkinter，任何异常都吞掉
    （theme 模块要保持可被无 tkinter 环境导入）。
    """
    c = palette or colors()
    try:
        win.configure(background=c["BG"])
    except Exception:
        pass
    return c

