# -*- coding: utf-8 -*-
"""添加/编辑邮箱账户对话框。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from core.account import Account, AccountManager


class AccountDialog(tk.Toplevel):
    """录入：显示名 / 邮箱 / 密码 / IMAP 服务器 / 端口 / SSL。

    保存后回调 on_saved(account, password)。
    """

    def __init__(self, master, manager: AccountManager,
                 account: Account | None = None, on_saved=None):
        super().__init__(master)
        self.manager = manager
        self.account = account
        self.on_saved = on_saved
        self.title("编辑账户" if account else "添加账户")
        self.resizable(False, False)
        self.grab_set()  # 模态

        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=12, pady=10)

        row_counter = [0]

        def row(label, widget_factory):
            r = row_counter[0]
            row_counter[0] += 1
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="e", **pad)
            w = widget_factory()
            w.grid(row=r, column=1, sticky="we", **pad)
            return w

        self.var_name = tk.StringVar()
        self.var_email = tk.StringVar(value=account.email if account else "")
        self.var_pass = tk.StringVar()
        self.var_host = tk.StringVar(value=account.imap_host if account else "")
        self.var_port = tk.StringVar(value=str(account.imap_port if account else 993))
        self.var_ssl = tk.BooleanVar(value=account.ssl if account else True)
        folder = account.folder if account else "INBOX"
        self.var_folder = tk.StringVar(value=folder or "INBOX")

        w0 = row("显示名：", lambda: ttk.Entry(frm, textvariable=self.var_name, width=30))
        w1 = row("邮箱地址：", lambda: ttk.Entry(frm, textvariable=self.var_email, width=30))
        w2 = row("密码/授权码：", lambda: ttk.Entry(frm, textvariable=self.var_pass,
                                                   width=30, show="*"))
        w3 = row("IMAP 服务器：", lambda: ttk.Entry(frm, textvariable=self.var_host, width=30))
        w4 = row("端口：", lambda: ttk.Entry(frm, textvariable=self.var_port, width=10))
        w5 = row("SSL：", lambda: ttk.Checkbutton(frm, variable=self.var_ssl))

        # 收信文件夹：可手填，也可点「获取」从服务器拉取列表
        folder_cell = ttk.Frame(frm)
        self.cmb_folder = ttk.Combobox(folder_cell, textvariable=self.var_folder, width=22)
        self.cmb_folder.pack(side="left", fill="x", expand=True)
        self.btn_fetch_folders = ttk.Button(folder_cell, text="获取",
                                            command=self._fetch_folders)
        self.btn_fetch_folders.pack(side="left", padx=(6, 0))
        self.lbl_folder_tip = ttk.Label(folder_cell, foreground="#888", text="")
        self.lbl_folder_tip.pack(side="left", padx=(6, 0))
        w6 = row("收信文件夹：", lambda: folder_cell)

        w1.bind("<FocusOut>", self._autofill_host)
        for w in (w0, w1, w2, w3, w4, w5, w6):
            frm.columnconfigure(1, weight=1)

        hint = ttk.Label(self, foreground="#888",
                         text="提示：QQ/163 等国内邮箱需在网页邮箱设置中开启 IMAP，"
                              "并使用「授权码」而非登录密码。")
        hint.pack(anchor="w", padx=12)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=8)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="保存", command=self._save).pack(side="right")

    def _autofill_host(self, _evt=None):
        if self.var_host.get().strip():
            return
        email_addr = self.var_email.get().strip()
        if "@" in email_addr:
            host, port = Account.guess_host(email_addr)
            if host:
                self.var_host.set(host)
                if not self.var_port.get().strip() or self.var_port.get() == "993":
                    self.var_port.set(str(port))

    def _fetch_folders(self):
        """子线程连接服务器 LIST 文件夹，成功后回填下拉列表。"""
        host = self.var_host.get().strip()
        email_addr = self.var_email.get().strip()
        password = self.var_pass.get()
        if not password and self.account:
            password = self.manager.password(self.account.id)
        if not host or "@" not in email_addr:
            self.lbl_folder_tip.configure(text="请先填写邮箱与服务器")
            return
        try:
            port = int(self.var_port.get().strip() or 993)
        except ValueError:
            self.lbl_folder_tip.configure(text="端口必须是数字")
            return

        def worker():
            from core.mail_client import MailClient
            acc_probe = Account(id="probe", name="", email=email_addr,
                                imap_host=host, imap_port=port,
                                ssl=self.var_ssl.get())
            try:
                folders = MailClient.list_folders(acc_probe, password)
            except Exception as e:
                self.after(0, lambda: self.lbl_folder_tip.configure(
                    text=f"获取失败：{type(e).__name__}"))
                return

            def apply():
                self.cmb_folder.configure(values=folders)
                self.lbl_folder_tip.configure(text=f"共 {len(folders)} 个文件夹")
            self.after(0, apply)

        self.lbl_folder_tip.configure(text="正在连接…")
        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _save(self):
        email_addr = self.var_email.get().strip()
        password = self.var_pass.get()
        host = self.var_host.get().strip()
        if "@" not in email_addr:
            messagebox.showwarning("一邮通", "请填写正确的邮箱地址", parent=self)
            return
        if not host:
            host, port = Account.guess_host(email_addr)
        try:
            port = int(self.var_port.get().strip() or 993)
        except ValueError:
            messagebox.showwarning("一邮通", "端口必须是数字", parent=self)
            return
        if not password:
            messagebox.showwarning("一邮通", "请填写密码或授权码", parent=self)
            return

        name = self.var_name.get().strip() or email_addr
        folder = self.var_folder.get().strip() or "INBOX"
        if self.account:
            self.account.name = name
            self.account.email = email_addr
            self.account.imap_host = host
            self.account.imap_port = port
            self.account.ssl = self.var_ssl.get()
            self.account.folder = folder
            self.manager.update(self.account, password=password)
            acc, pwd = self.account, password
        else:
            acc = self.manager.add(name, email_addr, password,
                                   imap_host=host, imap_port=port,
                                   ssl=self.var_ssl.get())
            acc.folder = folder
            self.manager.update(acc, password=password)
            pwd = password
        if self.on_saved:
            self.on_saved(acc, pwd)
        self.destroy()
