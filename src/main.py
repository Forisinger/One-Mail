# -*- coding: utf-8 -*-
"""一邮通 OneMail 程序入口。

用法：
    python main.py [--minimized]

--minimized：静默启动到托盘（开机自启时使用）。
"""
from __future__ import annotations

import queue
import sys
import os
from datetime import datetime

# 允许 python src/main.py 与打包 exe 两种运行方式
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk

from core.account import AccountManager
from core.scheduler import Scheduler, EV_NEW_MAIL, EV_STATUS
from notify import send as notify_send
from storage import config as config_store, database
from storage.config import data_dir
from ui.main_window import MainWindow
from ui.tray import Tray, CMD_SHOW, CMD_FETCH_NOW, CMD_MARK_ALL, CMD_TOGGLE_PAUSE, CMD_QUIT


class App:
    def __init__(self, start_minimized: bool):
        self.cfg = config_store.load()
        self.manager = AccountManager()
        self.scheduler = Scheduler(self.manager)
        self.tray_commands: queue.Queue = queue.Queue()

        database.init()

        self.root = tk.Tk()
        self.window = MainWindow(self.root, self.manager, self.scheduler)
        self.tray = Tray(self.tray_commands)

        self.paused = False
        self.root.bind("<<UnreadChanged>>", lambda e: self.update_badge())
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        self.update_badge()
        self.scheduler.start_all()
        self._log("程序启动")
        self.root.after(400, self.window.prompt_missing_password)
        self._poll_events()

        if not start_minimized:
            self.root.deiconify()
        else:
            self.root.withdraw()
        self.root.mainloop()

    # ---------- 托盘 ----------
    def hide_to_tray(self):
        self.root.withdraw()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def update_badge(self):
        self.tray.set_unread(database.unread_count())

    # ---------- 事件循环（UI 线程 500ms 轮询，开销可忽略） ----------
    def _poll_events(self):
        # 1) 收信引擎事件
        while True:
            try:
                evt = self.scheduler.events.get_nowait()
            except queue.Empty:
                break
            if evt["type"] == EV_NEW_MAIL:
                self._handle_new_mail(evt["account"], evt["mails"])
            elif evt["type"] == EV_STATUS:
                acc, text = evt["account"], evt["text"]
                self.window.set_status(f"[{acc.name}] {text}")
                self._log(f"[{acc.email}] {text}")
        # 2) 托盘命令
        while True:
            try:
                cmd = self.tray_commands.get_nowait()
            except queue.Empty:
                break
            self._handle_command(cmd["cmd"])
        self.root.after(500, self._poll_events)

    @staticmethod
    def _log(msg: str):
        """轻量日志：状态/异常落盘，便于排查。"""
        try:
            with open(os.path.join(data_dir(), "onemail.log"), "a",
                      encoding="utf-8") as f:
                f.write(f"{datetime.now():%m-%d %H:%M:%S} {msg}\n")
        except OSError:
            pass

    def _handle_new_mail(self, account, mails):
        new = database.insert_mails(account.id, mails)
        self.window.full_refresh()
        self.update_badge()
        if new:
            first = new[0]
            title = f"一邮通 · {account.name}"
            msg = f"{first['from_name'] or first['from_addr']}\n{first['subject']}"
            if len(new) > 1:
                msg += f"（等 {len(new)} 封新邮件）"
            notify_send(self.tray.icon, title, msg)
            self.window.set_status(f"[{account.name}] 收到 {len(new)} 封新邮件")

    def _handle_command(self, cmd: str):
        if cmd == CMD_SHOW:
            self.show_window()
        elif cmd == CMD_FETCH_NOW:
            self.show_window()
            self.window.fetch_now()
        elif cmd == CMD_MARK_ALL:
            database.mark_all_read()
            self.window.full_refresh()
            self.update_badge()
        elif cmd == CMD_TOGGLE_PAUSE:
            self.paused = not self.paused
            self.tray.set_paused(self.paused)
            if self.paused:
                self.scheduler.stop_all()
                self.window.set_status("收信已暂停")
            else:
                self.scheduler.start_all()
                self.window.set_status("收信已恢复")
        elif cmd == CMD_QUIT:
            self.quit()

    def quit(self):
        try:
            self.scheduler.stop_all()
            self.tray.stop()
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)  # 确保守护线程与托盘线程全部退出


def main():
    start_minimized = "--minimized" in sys.argv or bool(
        config_store.load().get("settings", {}).get("start_minimized", True)
    )
    App(start_minimized)


if __name__ == "__main__":
    main()
