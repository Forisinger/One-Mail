# -*- coding: utf-8 -*-
"""账户管理对话框（v1.11.0）。

把原先散落在主界面顶栏的「添加 / 编辑 / 删除账户」三个入口合并到同一界面：
列表展示全部账户（显示名 / 邮箱 / 认证方式 / 服务器 / 状态），底部提供
添加、编辑、删除、启用停用与关闭；双击一行等于编辑。

职责边界：
- 只处理账户增删改的交互与确认；网络线程的启停一律交给 Scheduler
  （stop 内部会 stop + 有界 join，避免幽灵邮件写回已删账户）
- 删除后本地邮件缓存一并清理，与主界面旧行为一致
- 任何变更完成后回调主界面刷新（on_saved / on_removed）
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from core.account import AccountManager
from core.scheduler import Scheduler
from storage import database as db
from . import i18n
from . import theme as theme_mod
from .account_dialog import AccountDialog


class AccountsDialog(tk.Toplevel):
    """账户列表 + 增删改，统一入口。"""

    def __init__(self, master, manager: AccountManager, scheduler: Scheduler,
                 on_saved=None, on_removed=None, preselect: str | None = None):
        super().__init__(master)
        self.manager = manager
        self.scheduler = scheduler
        self.on_saved = on_saved
        self.on_removed = on_removed
        self._selected_id = preselect
        self.C = theme_mod.window_colors(self)   # 窗口底跟随主题（v1.11.2）

        self.title(i18n.t("账户管理"))
        self.geometry("660x420")
        self.minsize(560, 340)
        self.transient(master)
        self.grab_set()

        wrap = ttk.Frame(self, padding=(12, 10))
        wrap.pack(fill="both", expand=True)

        ttk.Label(wrap, text=i18n.t("账户列表（双击编辑，Enter 编辑 / Delete 删除）")).pack(
            anchor="w", pady=(0, 6))
        cols = ("name", "email", "auth", "server", "state")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                 selectmode="browse")
        for cid, text, width, anchor in (
            ("name", i18n.t("显示名"), 120, "w"),
            ("email", i18n.t("邮箱"), 190, "w"),
            ("auth", i18n.t("认证"), 70, "center"),
            ("server", i18n.t("服务器"), 180, "w"),
            ("state", i18n.t("状态"), 70, "center"),
        ):
            self.tree.heading(cid, text=text)
            self.tree.column(cid, width=width, anchor=anchor,
                             stretch=(cid in ("email", "server")))
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.edit_account())
        # 键盘操作：Enter=编辑、Delete=删除、Esc=关闭（v1.11.4）
        self.tree.bind("<Return>", lambda e: self.edit_account())
        self.tree.bind("<Delete>", lambda e: self.remove_account())
        self.bind("<Escape>", lambda e: self.destroy())

        btns = ttk.Frame(self, padding=(12, 0, 12, 10))
        btns.pack(fill="x")
        ttk.Button(btns, text=i18n.t("＋ 添加账户"),
                   command=self.add_account).pack(side="left")
        ttk.Button(btns, text=i18n.t("✎ 编辑账户"),
                   command=self.edit_account).pack(side="left", padx=6)
        ttk.Button(btns, text=i18n.t("－ 删除账户"),
                   command=self.remove_account).pack(side="left")
        ttk.Button(btns, text=i18n.t("启用 / 停用"),
                   command=self.toggle_enabled).pack(side="left", padx=(18, 0))
        ttk.Button(btns, text=i18n.t("关闭"),
                   command=self.destroy).pack(side="right")

        self.refresh()

    # ---------- 列表 ----------
    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for acc in self.manager.all():
            auth = "OAuth2" if getattr(acc, "auth_type", "password") == "oauth2" \
                else i18n.t("授权码")
            self.tree.insert(
                "", "end", iid=acc.id,
                values=(acc.name,
                        acc.email,
                        auth,
                        f"{acc.imap_host}:{acc.imap_port}",
                        i18n.t("已启用") if acc.enabled else i18n.t("已停用")))
        if self._selected_id and self.tree.exists(self._selected_id):
            self.tree.selection_set(self._selected_id)

    def _selected_account(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(i18n.t("一邮通"), i18n.t("请先选中一个账户"),
                                parent=self)
            return None
        acc = self.manager.get(sel[0])
        if acc is None:
            self.refresh()
            return None
        return acc

    # ---------- 增删改 ----------
    def add_account(self):
        AccountDialog(self, self.manager, on_saved=self._saved)

    def edit_account(self):
        acc = self._selected_account()
        if acc is None:
            return
        AccountDialog(self, self.manager, account=acc, on_saved=self._saved)

    def _saved(self, acc, password):
        self._selected_id = acc.id
        self.refresh()
        # 添加/编辑子对话框的 grab 会随其销毁而释放，导致本窗口失去模态
        self.after(10, self._regrab)
        if self.on_saved:
            try:
                self.on_saved(acc, password)
            except Exception:
                pass

    def _regrab(self):
        try:
            if self.winfo_exists():
                self.grab_set()
        except tk.TclError:
            pass

    def remove_account(self):
        acc = self._selected_account()
        if acc is None:
            return
        if not messagebox.askyesno(
                i18n.t("一邮通"),
                i18n.t("删除账户 {name}？\n该账户的本地邮件缓存将一并删除。")
                .format(name=acc.name), parent=self):
            return
        # 先停线程（stop 内含 stop + 有界 join），再删配置与缓存，
        # 否则卡在建连中的线程可能把邮件写回已删除账户
        self.scheduler.stop_account(acc.id)
        self.manager.remove(acc.id)
        db.delete_account_mails(acc.id)
        self._selected_id = None
        self.refresh()
        if self.on_removed:
            try:
                self.on_removed(acc.id)
            except Exception:
                pass

    def toggle_enabled(self):
        """切换启用/停用。收信线程的启停交给主界面回调（单一职责：
        线程生命周期只由 _on_account_saved 按 acc.enabled 决定）。"""
        acc = self._selected_account()
        if acc is None:
            return
        acc.enabled = not acc.enabled
        self.manager.update(acc)
        self._selected_id = acc.id
        self.refresh()
        if self.on_saved:
            try:
                self.on_saved(acc, None)
            except Exception:
                pass
        else:
            # 无回调（独立使用）：自行管理线程
            if acc.enabled:
                self.scheduler.start_account(acc)
            else:
                self.scheduler.stop_account(acc.id)
