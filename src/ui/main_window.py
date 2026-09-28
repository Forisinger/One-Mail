# -*- coding: utf-8 -*-
"""主窗口：左侧账户列表（来源标注/筛选）+ 右上邮件列表 + 右下阅读区。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from core.account import Account, AccountManager
from storage import database as db
from core.scheduler import Scheduler
from .account_dialog import AccountDialog


class MainWindow:
    def __init__(self, root: tk.Tk, manager: AccountManager, scheduler: Scheduler):
        self.root = root
        self.manager = manager
        self.scheduler = scheduler
        self._filter_account: str | None = None   # None = 全部账户

        root.title("一邮通 OneMail")
        root.geometry("1000x640")
        root.minsize(760, 480)

        self._build_toolbar()
        self._build_panes()
        self._build_statusbar()
        self.refresh_accounts()
        self.refresh_mails()

    # ---------- 布局 ----------
    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=4)
        bar.pack(fill="x")
        ttk.Button(bar, text="立即收信", command=self.fetch_now).pack(side="left", padx=2)
        ttk.Button(bar, text="全部已读", command=self.mark_all_read).pack(side="left", padx=2)
        ttk.Button(bar, text="添加账户", command=self.add_account).pack(side="left", padx=2)
        ttk.Button(bar, text="编辑账户", command=self.edit_account).pack(side="left", padx=2)
        ttk.Button(bar, text="删除账户", command=self.remove_account).pack(side="left", padx=2)
        ttk.Button(bar, text="标记已读", command=self.mark_selected_read).pack(side="left", padx=2)

    def _build_panes(self):
        pane = ttk.Panedwindow(self.root, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=4, pady=2)

        # 左：账户列表（来源标注）
        left = ttk.LabelFrame(pane, text=" 邮箱账户（点击筛选来源） ", padding=4)
        self.lst_accounts = tk.Listbox(left, activestyle="none", exportselection=False)
        self.lst_accounts.pack(fill="both", expand=True)
        self.lst_accounts.bind("<<ListboxSelect>>", self._on_account_select)
        pane.add(left, weight=1)

        # 右：上下分栏
        right = ttk.Panedwindow(pane, orient="vertical")
        pane.add(right, weight=3)

        cols = ("account", "from", "subject", "date")
        frame_top = ttk.Frame(right)
        self.tree = ttk.Treeview(frame_top, columns=cols, show="headings", selectmode="browse")
        for cid, text, width, anchor in (
            ("account", "来源", 110, "w"),
            ("from", "发件人", 160, "w"),
            ("subject", "主题", 380, "w"),
            ("date", "时间", 140, "w"),
        ):
            self.tree.heading(cid, text=text)
            self.tree.column(cid, width=width, anchor=anchor, stretch=(cid == "subject"))
        vsb = ttk.Scrollbar(frame_top, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._on_mail_open)
        self.tree.tag_configure("unread", font=("", 10, "bold"))
        right.add(frame_top, weight=3)

        frame_body = ttk.LabelFrame(right, text=" 邮件正文 ", padding=2)
        self.txt_body = tk.Text(frame_body, wrap="word", state="disabled",
                                relief="flat", padx=8, pady=6)
        bsb = ttk.Scrollbar(frame_body, orient="vertical", command=self.txt_body.yview)
        self.txt_body.configure(yscrollcommand=bsb.set)
        self.txt_body.pack(side="left", fill="both", expand=True)
        bsb.pack(side="right", fill="y")
        right.add(frame_body, weight=2)

    def _build_statusbar(self):
        self.var_status = tk.StringVar(value="就绪")
        bar = ttk.Label(self.root, textvariable=self.var_status,
                        anchor="w", relief="sunken", padding=(6, 2))
        bar.pack(fill="x", side="bottom")

    # ---------- 数据刷新 ----------
    def refresh_accounts(self):
        sel = self._filter_account
        self.lst_accounts.delete(0, "end")
        total_unread = db.unread_count()
        self.lst_accounts.insert("end", f"  全部邮件{'  (' + str(total_unread) + ' 未读)' if total_unread else ''}")
        for acc in self.manager.all():
            n = db.unread_count(acc.id)
            mark = "● " if n else "  "
            state = "" if acc.enabled else "（已停用）"
            self.lst_accounts.insert("end", f"{mark}{acc.name}{state}  ({acc.email})"
                                            + (f"  [{n}]" if n else ""))
        # 恢复选中
        accounts = ["__ALL__"] + [a.id for a in self.manager.all()]
        if sel in accounts:
            self.lst_accounts.selection_set(accounts.index(sel))

    def refresh_mails(self):
        self.tree.delete(*self.tree.get_children())
        for row in db.list_mails(self._filter_account):
            acc = self.manager.get(row["account_id"])
            acc_name = acc.name if acc else row["account_id"]
            subj = ("📎 " if row["has_attachment"] else "") + (row["subject"] or "")
            tag = ("unread",) if not row["is_read"] else ()
            self.tree.insert("", "end", iid=str(row["id"]),
                             values=(acc_name, row["from_name"] or row["from_addr"],
                                     subj, (row["received_at"] or "")[:16]),
                             tags=tag)

    def full_refresh(self):
        self.refresh_accounts()
        self.refresh_mails()

    # ---------- 交互 ----------
    def _on_account_select(self, _evt=None):
        sel = self.lst_accounts.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx == 0:
            self._filter_account = None
        else:
            accounts = self.manager.all()
            if idx - 1 < len(accounts):
                self._filter_account = accounts[idx - 1].id
        self.refresh_mails()

    def _on_mail_open(self, _evt=None):
        sel = self.tree.selection()
        if not sel:
            return
        mail = db.get_mail(int(sel[0]))
        if mail is None:
            return
        if not mail["is_read"]:
            db.mark_read(mail["id"])
            self.refresh_mails()
            self.refresh_accounts()
            self.root.event_generate("<<UnreadChanged>>", when="tail")
        acc = self.manager.get(mail["account_id"])
        header = (
            f"来源：{acc.name if acc else mail['account_id']} <{acc.email if acc else ''}>\n"
            f"发件人：{mail['from_name']} <{mail['from_addr']}>\n"
            f"主题：{mail['subject']}\n"
            f"时间：{mail['received_at']}\n"
            + "-" * 60 + "\n\n"
        )
        self.txt_body.configure(state="normal")
        self.txt_body.delete("1.0", "end")
        self.txt_body.insert("1.0", header + (mail["body_text"] or "（无正文/解析失败）"))
        self.txt_body.configure(state="disabled")

    def fetch_now(self):
        n = 0
        for acc in self.manager.enabled():
            client = self.scheduler.client(acc.id)
            if client is not None and not client.stopped:
                n += 1
        self.var_status.set(f"已请求 {n} 个账户收信（推送账户将在数秒内更新）")

    def mark_all_read(self):
        db.mark_all_read(self._filter_account)
        self.full_refresh()
        self.root.event_generate("<<UnreadChanged>>", when="tail")

    def mark_selected_read(self):
        sel = self.tree.selection()
        if not sel:
            return
        db.mark_read(int(sel[0]))
        self.refresh_mails()
        self.refresh_accounts()
        self.root.event_generate("<<UnreadChanged>>", when="tail")

    def add_account(self):
        AccountDialog(self.root, self.manager, on_saved=self._on_account_saved)

    def edit_account(self):
        acc = self._selected_account()
        if acc is None:
            messagebox.showinfo("一邮通", "请先在左侧列表选中要编辑的账户")
            return
        AccountDialog(self.root, self.manager, account=acc,
                      on_saved=lambda a, p: self._on_account_saved(a, p))

    def prompt_missing_password(self):
        """启动时若有账户缺密码，自动弹出编辑框录入授权码。"""
        for acc in self.manager.all():
            if acc.enabled and not self.manager.password(acc.id):
                self.var_status.set(f"账户 {acc.name} 缺少授权码，请输入")
                AccountDialog(self.root, self.manager, account=acc,
                              on_saved=lambda a, p: self._on_account_saved(a, p))
                return

    def _selected_account(self) -> Account | None:
        sel = self.lst_accounts.curselection()
        if not sel or sel[0] == 0:
            return None
        accounts = self.manager.all()
        idx = sel[0] - 1
        return accounts[idx] if 0 <= idx < len(accounts) else None

    def _on_account_saved(self, acc: Account, password: str):
        self.scheduler.start_account(acc)
        self.full_refresh()
        self.var_status.set(f"账户 {acc.name} 已保存，开始连接 {acc.imap_host} …")

    def remove_account(self):
        acc = self._selected_account()
        if acc is None:
            messagebox.showinfo("一邮通", "请先在左侧列表选中要删除的账户")
            return
        if not messagebox.askyesno("一邮通",
                                   f"删除账户 {acc.name}？\n该账户的本地邮件缓存将一并删除。"):
            return
        self.scheduler.stop_account(acc.id)
        self.manager.remove(acc.id)
        db.delete_account_mails(acc.id)
        self._filter_account = None
        self.full_refresh()
        self.root.event_generate("<<UnreadChanged>>", when="tail")

    def set_status(self, text: str):
        self.var_status.set(text)
