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
import traceback
from datetime import datetime

# 允许 python src/main.py 与打包 exe 两种运行方式
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk

from core.account import AccountManager
from core.flag_sync import FlagSync
from core.scheduler import Scheduler, EV_NEW_MAIL, EV_STATUS
from notify import send as notify_send
from single_instance import acquire, notify_running_instance, start_watcher
from storage import config as config_store, database
from storage.config import data_dir
from ui import i18n
from ui.main_window import MainWindow
from ui.tray import (Tray, CMD_SHOW, CMD_FETCH_NOW, CMD_MARK_ALL,
                     CMD_TOGGLE_PAUSE, CMD_TOGGLE_SYNC, CMD_QUIT)


class App:
    def __init__(self, start_minimized: bool):
        i18n.init()   # 语言在构造任何 UI 之前确定（v1.9.0）
        self.cfg = config_store.load()
        self.manager = AccountManager()
        self.scheduler = Scheduler(self.manager)
        self.tray_commands: queue.Queue = queue.Queue()

        database.init()

        # 已读状态同步（v1.7.0）：本地标已读 → 后台短连接 UID STORE \Seen。
        # 必须在 MainWindow 之前创建（构造函数要注入）。
        def _get_credentials(account_id):
            acc = self.manager.get(account_id)
            if acc is None:
                return None, None
            return acc, self.manager.password(acc.id)

        self.flag_sync = FlagSync(
            _get_credentials,
            # 每次现读配置：托盘开关切换后立即生效（用启动快照会让开关形同虚设）
            enabled=lambda: config_store.load().get("settings", {}).get(
                "sync_read_flags", True),
            log=self._log,
        )

        self.root = tk.Tk()
        self.window = MainWindow(self.root, self.manager, self.scheduler,
                                 flag_sync=self.flag_sync)
        self.tray = Tray(self.tray_commands)

        self.paused = False
        self.root.bind("<<UnreadChanged>>", lambda e: self.update_badge())
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        self.update_badge()
        self.scheduler.start_all()
        self._log(i18n.t("程序启动"))
        self.root.after(400, self.window.prompt_missing_password)
        self._poll_events()

        # 其他实例二次启动 exe 时，唤醒主窗口置前
        start_watcher(
            lambda: self.tray_commands.put({"cmd": CMD_SHOW}),
            error_log=self._log,
        )

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
        # Windows 下跨应用抢焦点受限：临时置顶再取消，确保真正弹到最上层
        self.root.attributes("-topmost", True)
        self.root.after(200, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

    def update_badge(self):
        self.tray.set_unread(database.unread_count())

    # ---------- 事件循环（UI 线程 500ms 轮询，开销可忽略） ----------
    def _poll_events(self):
        # 防护：任何处理器异常都不能切断 after 链——否则收信事件与托盘
        # 命令永久失联（程序"活着但失聪"），且毫无可见征兆
        try:
            self._drain_events()
        except Exception as e:
            self._log(f"事件处理异常: {e!r}")
            traceback.print_exc()
        finally:
            self.root.after(500, self._poll_events)

    def _drain_events(self):
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
                self.window.set_account_status(acc.id, text)
                self.window.set_status(f"[{acc.name}] {text}")
                self._log(f"[{acc.email}] {text}")
        # 2) 托盘命令
        while True:
            try:
                cmd = self.tray_commands.get_nowait()
            except queue.Empty:
                break
            self._handle_command(cmd["cmd"])

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
        # 邮件已在收信线程同步入库（水位推进依赖入库完成），
        # 这里只负责刷新 UI 与通知；mails 只含真正新入库的邮件
        self.window.full_refresh()
        self.update_badge()
        if mails:
            first = mails[0]
            title = i18n.t("一邮通 · {name}").format(name=account.name)
            msg = f"{first['from_name'] or first['from_addr']}\n{first['subject']}"
            if len(mails) > 1:
                msg += f"（{len(mails)}）"
            notify_send(self.tray.icon, title, msg)
            self.window.set_status(
                i18n.t("[{name}] 收到 {n} 封新邮件").format(
                    name=account.name, n=len(mails)))

    def _handle_command(self, cmd: str):
        if cmd == CMD_SHOW:
            self.show_window()
        elif cmd == CMD_FETCH_NOW:
            self.show_window()
            self.window.fetch_now()
        elif cmd == CMD_MARK_ALL:
            # 托盘语义 = 全部账户（与旧行为一致）；工具栏按钮才尊重当前筛选
            self.window.mark_all_read(account_id=None)
            self.update_badge()
        elif cmd == CMD_TOGGLE_SYNC:
            self._toggle_sync_read()
        elif cmd == CMD_TOGGLE_PAUSE:
            self.paused = not self.paused
            self.tray.set_paused(self.paused)
            if self.paused:
                self.scheduler.stop_all()
                self.window.set_status(i18n.t("收信已暂停"))
            else:
                self.scheduler.start_all()
                self.window.set_status(i18n.t("收信已恢复"))
        elif cmd == CMD_QUIT:
            self.quit()

    def _toggle_sync_read(self):
        """切换「同步已读到服务器」设置（托盘勾选项）。"""
        try:
            cfg = config_store.load()
            cur = bool(cfg.get("settings", {}).get("sync_read_flags", True))
            cfg.setdefault("settings", {})["sync_read_flags"] = not cur
            config_store.save(cfg)
            state = i18n.t("已开启") if not cur else i18n.t("已关闭")
            self.window.set_status(
                i18n.t("已读状态同步到服务器：{state}").format(state=state))
            self._log(f"sync_read_flags -> {not cur}")
        except Exception as e:
            self._log(f"切换已读同步设置失败: {e!r}")

    def quit(self):
        try:
            # 兜底：退出前把已排队的事件处理完（确保新邮件已入库/界面已刷新）
            self._drain_events()
        except Exception:
            pass
        try:
            self.scheduler.stop_all()
            self.flag_sync.stop()
            self.tray.stop()
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)  # 确保守护线程与托盘线程全部退出


def main():
    # 单实例：已有 OneMail 在运行时，唤醒其主窗口并退出本进程
    if not acquire():
        notify_running_instance()
        return
    # 双击 exe 直接显示主窗口；仅开机自启（注册表项带 --minimized）静默进托盘
    start_minimized = "--minimized" in sys.argv
    App(start_minimized)


if __name__ == "__main__":
    main()
