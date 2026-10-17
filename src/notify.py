# -*- coding: utf-8 -*-
"""Windows 通知：优先 pystray 原生气泡（零额外依赖）。

pystray 在 Windows 上通过 Shell_NotifyIcon 气泡通知实现 icon.notify()，
不引入 toast 库；后续如需跳转点击可再换 win11toast。
"""
from __future__ import annotations


def send(tray_icon, title: str, message: str, error_log=None):
    """通过托盘图标发系统气泡通知。tray_icon 为 pystray.Icon。

    v1.11.6：失败不再裸吞——图标未就绪/Shell_NotifyIcon 失败时用户
    "收不到新邮件提醒"却毫无线索，至少落一条日志。
    """
    try:
        tray_icon.notify(message, title)
    except Exception as e:
        if error_log:
            try:
                error_log(f"发送通知失败: {e!r}")
            except Exception:
                pass


def clear(tray_icon):
    try:
        tray_icon.remove_notification()
    except Exception:
        pass
