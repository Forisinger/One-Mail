# -*- coding: utf-8 -*-
"""写信窗口：新邮件与回复共用。

- 账户下拉框（仅列出已存授权码的账户）
- 收件人支持逗号/分号/空格分隔
- 附件可增删；发送在后台线程执行，界面全程可响应
- 完成后通过 root.after 回 UI 线程弹结果，杜绝跨线程碰 Tk
"""
from __future__ import annotations

import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core.account import Account, AccountManager
from core import smtp_client

ADDR_SPLIT = re.compile(r"[,;，；\s]+")
ADDR_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

BG = "#eef1f6"
CARD = "#ffffff"
TEXT = "#1f2937"
GRAY = "#6b7280"
ACCENT = "#1e64dc"
FONT_UI = ("Microsoft YaHei UI", 10)
FONT_UI_B = ("Microsoft YaHei UI", 10, "bold")


class ComposeWindow:
    def __init__(self, root: tk.Tk, manager: AccountManager,
                 account: Account | None = None, to: str = "",
                 subject: str = "", body: str = ""):
        self.root = root
        self.manager = manager
        self.attachments: list[str] = []
        self._sending = False

        self.win = tk.Toplevel(root)
        self.win.title("写邮件 · 一邮通")
        self.win.geometry("640x560")
        self.win.minsize(520, 420)
        self.win.configure(background=CARD)
        self.win.transient(root)

        frm = ttk.Frame(self.win, style="Card.TFrame")
        frm.pack(fill="both", expand=True, padx=14, pady=10)

        def row(r: int, label: str) -> ttk.Frame:
            ttk.Label(frm, text=label, style="Card.TLabel",
                      font=FONT_UI_B).grid(row=r, column=0, sticky="ne",
                                           padx=(0, 8), pady=6)
            return frm

        # 发件账户
        row(0, "发件账户")
        self.var_account = tk.StringVar()
        self.cmb_account = ttk.Combobox(frm, textvariable=self.var_account,
                                        state="readonly", font=FONT_UI)
        self.cmb_account.grid(row=0, column=1, sticky="we", pady=6)
        self._accounts = [a for a in manager.all() if manager.password(a.id)]
        self.cmb_account["values"] = [
            f"{a.name} <{a.email}>" for a in self._accounts]
        if account and account in self._accounts:
            self.cmb_account.current(self._accounts.index(account))
        elif self._accounts:
            self.cmb_account.current(0)

        # 收件人
        row(1, "收件人")
        self.var_to = tk.StringVar(value=to)
        ent_to = tk.Entry(frm, textvariable=self.var_to, font=FONT_UI,
                          bg=CARD, fg=TEXT, relief="solid", bd=1,
                          highlightthickness=0, insertbackground=TEXT)
        ent_to.grid(row=1, column=1, sticky="we", pady=6)

        # 主题
        row(2, "主题")
        self.var_subject = tk.StringVar(value=subject)
        ent_sub = tk.Entry(frm, textvariable=self.var_subject, font=FONT_UI,
                           bg=CARD, fg=TEXT, relief="solid", bd=1,
                           highlightthickness=0, insertbackground=TEXT)
        ent_sub.grid(row=2, column=1, sticky="we", pady=6)

        # 正文
        row(3, "正文")
        self.txt_body = tk.Text(frm, font=FONT_UI, bg=CARD, fg=TEXT,
                                relief="solid", bd=1, wrap="word",
                                height=12, insertbackground=TEXT,
                                undo=True)
        self.txt_body.grid(row=3, column=1, sticky="nsew", pady=6)
        self.txt_body.insert("1.0", body)

        # 附件
        row(4, "附件")
        att_bar = ttk.Frame(frm, style="Card.TFrame")
        att_bar.grid(row=4, column=1, sticky="we", pady=6)
        ttk.Button(att_bar, text="添加附件…", command=self._add_attachment
                   ).pack(side="left")
        ttk.Button(att_bar, text="移除选中", command=self._remove_attachment
                   ).pack(side="left", padx=6)
        self.lst_att = tk.Listbox(att_bar, height=4, font=FONT_UI, bg=CARD,
                                  fg=TEXT, relief="solid", bd=1,
                                  selectbackground=ACCENT,
                                  activestyle="none")
        self.lst_att.pack(side="left", fill="x", expand=True, padx=(8, 0))

        # 发送与状态
        btn_bar = ttk.Frame(frm, style="Card.TFrame")
        btn_bar.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))
        self.var_status = tk.StringVar()
        tk.Label(btn_bar, textvariable=self.var_status, bg=CARD, fg=GRAY,
                 font=FONT_UI).pack(side="left", padx=(0, 10))
        self.btn_send = ttk.Button(btn_bar, text="发送", command=self.send)
        self.btn_send.pack(side="right")

        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(3, weight=1)
        ent_to.focus_set()

    # ---------- 附件 ----------
    def _add_attachment(self):
        paths = filedialog.askopenfilenames(parent=self.win, title="选择附件")
        for p in paths:
            if p not in self.attachments:
                self.attachments.append(p)
                self.lst_att.insert("end", p)

    def _remove_attachment(self):
        for i in reversed(self.lst_att.curselection()):
            self.lst_att.delete(i)
        self.attachments = list(self.lst_att.get(0, "end"))

    # ---------- 发送 ----------
    @staticmethod
    def parse_addresses(raw: str) -> list[str]:
        addrs = [a for a in ADDR_SPLIT.split(raw.strip()) if a]
        bad = [a for a in addrs if not ADDR_RE.match(a)]
        if bad:
            raise ValueError(f"收件人格式有误：{', '.join(bad)}")
        return addrs

    def send(self):
        if self._sending:
            return
        if not self._accounts:
            messagebox.showwarning("一邮通", "没有可用账户：请先在主窗口添加账户并填入授权码",
                                   parent=self.win)
            return
        try:
            addrs = self.parse_addresses(self.var_to.get())
        except ValueError as e:
            messagebox.showwarning("一邮通", str(e), parent=self.win)
            return
        if not addrs:
            messagebox.showwarning("一邮通", "请填写收件人", parent=self.win)
            return
        acc = self._accounts[self.cmb_account.current()]
        password = self.manager.password(acc.id)
        subject = self.var_subject.get().strip()
        body = self.txt_body.get("1.0", "end").rstrip("\n")
        files = list(self.attachments)

        self._sending = True
        self.btn_send.configure(state="disabled")
        self.var_status.set("正在发送…")

        def _work():
            ok, err = False, ""
            try:
                msg = smtp_client.send_mail(acc, password, addrs, subject,
                                            body, files)
                smtp_client.save_to_sent(acc, password, msg)
                ok = True
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
            self.root.after(0, lambda: self._on_sent(ok, err))

        threading.Thread(target=_work, name="onemail-send", daemon=True).start()

    def _on_sent(self, ok: bool, err: str):
        self._sending = False
        self.btn_send.configure(state="normal")
        if ok:
            self.var_status.set("已发送")
            messagebox.showinfo("一邮通", "发送成功", parent=self.win)
            self.win.destroy()
        else:
            self.var_status.set("发送失败")
            messagebox.showerror(
                "一邮通",
                f"发送失败：{err}\n\n常见原因：授权码错误、未开启 SMTP 服务、"
                f"附件过大或网络中断。", parent=self.win)
