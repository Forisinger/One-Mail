# -*- coding: utf-8 -*-
"""多账户调度器：每账户一条 MailClient 守护线程，事件入队供 UI 消费。

线程模型（低占用关键）：
- 主线程：tkinter UI
- 每启用账户 1 条 daemon 线程，IDLE 阻塞等待，不占 CPU
- 调度器本身不持有额外线程，仅做线程生命周期管理与事件转发
"""
from __future__ import annotations

import queue
import threading

from .account import Account, AccountManager
from .mail_client import MailClient
from .parser import ParsedMail

# 事件类型
EV_NEW_MAIL = "new_mail"       # {"account": Account, "mails": [dict]}
EV_STATUS = "status"           # {"account": Account, "text": str}


class Scheduler:
    def __init__(self, manager: AccountManager):
        self.manager = manager
        self.events: queue.Queue = queue.Queue()
        self._clients: dict[str, MailClient] = {}
        self._lock = threading.Lock()

    # ---------- 启动/停止 ----------
    def start_all(self):
        for acc in self.manager.enabled():
            self.start_account(acc)

    def stop_all(self):
        with self._lock:
            for c in self._clients.values():
                c.stop()
        # 不 join，daemon 线程随进程退出

    # ---------- 单账户管理 ----------
    def start_account(self, acc: Account):
        with self._lock:
            self._stop_client_locked(acc.id)
            if not self.manager.password(acc.id):
                # 未设置密码：不起收信线程，等用户在界面录入授权码
                self.events.put({"type": EV_STATUS, "account": acc,
                                 "text": "未设置密码/授权码，请在界面中编辑账户"})
                return
            client = MailClient(
                acc, self.manager.password(acc.id),
                on_new_mail=self._emit_new_mail, on_status=self._emit_status,
            )
            self._clients[acc.id] = client
        client.start()

    def stop_account(self, account_id: str):
        with self._lock:
            self._stop_client_locked(account_id)

    def _stop_client_locked(self, account_id: str):
        client = self._clients.pop(account_id, None)
        if client is not None:
            client.stop()

    def restart_account(self, acc: Account):
        self.start_account(acc)

    def client(self, account_id: str) -> MailClient | None:
        return self._clients.get(account_id)

    # ---------- 事件回调（MailClient 线程 -> 队列 -> UI 线程） ----------
    def _emit_new_mail(self, account: Account, mails: list[dict]):
        self.events.put({"type": EV_NEW_MAIL, "account": account, "mails": mails})

    def _emit_status(self, account: Account, text: str):
        self.events.put({"type": EV_STATUS, "account": account, "text": text})
