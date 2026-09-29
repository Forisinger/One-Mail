# -*- coding: utf-8 -*-
"""系统托盘：pystray 独立线程，未读角标动态刷新。

托盘菜单动作通过命令队列交给 UI 线程执行（跨线程安全）。
"""
from __future__ import annotations

import queue

import pystray

from . import icon as icon_mod

# 托盘 -> UI 的命令类型
CMD_SHOW = "show"
CMD_FETCH_NOW = "fetch_now"
CMD_MARK_ALL = "mark_all"
CMD_TOGGLE_PAUSE = "toggle_pause"
CMD_QUIT = "quit"


class Tray:
    def __init__(self, commands: queue.Queue):
        self._commands = commands
        self._paused = False
        self.icon = pystray.Icon(
            "OneMail",
            icon_mod.with_badge(0),
            title="一邮通 OneMail",
            menu=self._build_menu(),
        )
        try:
            self.icon.run_detached()
        except Exception:
            # 无托盘/Shell 环境（如 Server Core）：降级为无托盘运行，
            # 主窗口功能不受影响
            self.icon = None

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("打开主界面", self._emit(CMD_SHOW), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("立即收信", self._emit(CMD_FETCH_NOW)),
            pystray.MenuItem(
                lambda item: "恢复收信" if self._paused else "暂停收信",
                self._emit(CMD_TOGGLE_PAUSE),
            ),
            pystray.MenuItem("全部标为已读", self._emit(CMD_MARK_ALL)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._emit(CMD_QUIT)),
        )

    def _emit(self, cmd: str):
        def handler(icon, item):
            self._commands.put({"cmd": cmd})
        return handler

    # ---------- 状态更新（UI 线程调用） ----------
    def set_unread(self, count: int):
        try:
            self.icon.icon = icon_mod.with_badge(count)
            self.icon.title = f"一邮通 OneMail｜未读 {count}"
        except Exception:
            pass

    def set_paused(self, paused: bool):
        self._paused = paused

    def notify(self, title: str, message: str):
        try:
            self.icon.notify(message, title)
        except Exception:
            pass

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass
