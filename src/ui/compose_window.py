# -*- coding: utf-8 -*-
"""写信窗口：新邮件与回复共用。

- 账户下拉框（仅列出已存授权码的账户）
- 收件人/抄送/密送支持逗号、分号、空格分隔；BCC 由 send_message 自动剥离
- 正文支持基础富文本：加粗/斜体/下划线/字体颜色（tkinter 标签实现，零依赖）
- 附件可增删；发送在后台线程执行，界面全程可响应
- 完成后通过 root.after 回 UI 线程弹结果，杜绝跨线程碰 Tk
"""
from __future__ import annotations

import re
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from core.account import Account, AccountManager
from core import smtp_client
from . import richtext

ADDR_SPLIT = re.compile(r"[,;，；\s]+")
ADDR_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

BG = "#eef1f6"
CARD = "#ffffff"
TEXT = "#1f2937"
GRAY = "#6b7280"
ACCENT = "#1e64dc"
FONT_UI = ("Microsoft YaHei UI", 10)
FONT_UI_B = ("Microsoft YaHei UI", 10, "bold")

STYLE_BUTTONS = (
    ("B", "bold", ("Microsoft YaHei UI", 10, "bold")),
    ("I", "italic", ("Microsoft YaHei UI", 10, "italic")),
    ("U", "underline", ("Microsoft YaHei UI", 10, "underline")),
)


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
        self.win.geometry("640x600")
        self.win.minsize(520, 460)
        self.win.configure(background=CARD)
        self.win.transient(root)

        frm = ttk.Frame(self.win, style="Card.TFrame")
        frm.pack(fill="both", expand=True, padx=14, pady=10)

        def row(r: int, label: str) -> None:
            ttk.Label(frm, text=label, style="Card.TLabel",
                      font=FONT_UI_B).grid(row=r, column=0, sticky="ne",
                                           padx=(0, 8), pady=6)

        def entry(r: int, textvariable: tk.StringVar) -> tk.Entry:
            e = tk.Entry(frm, textvariable=textvariable, font=FONT_UI,
                         bg=CARD, fg=TEXT, relief="solid", bd=1,
                         highlightthickness=0, insertbackground=TEXT)
            e.grid(row=r, column=1, sticky="we", pady=6)
            return e

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

        # 收件人 / 抄送 / 密送
        row(1, "收件人")
        self.var_to = tk.StringVar(value=to)
        entry(1, self.var_to).focus_set()
        row(2, "抄送")
        self.var_cc = tk.StringVar()
        entry(2, self.var_cc)
        row(3, "密送")
        self.var_bcc = tk.StringVar()
        entry(3, self.var_bcc)

        # 主题
        row(4, "主题")
        self.var_subject = tk.StringVar(value=subject)
        entry(4, self.var_subject)

        # 正文（格式工具条 + 文本区）
        row(5, "正文")
        body_wrap = ttk.Frame(frm, style="Card.TFrame")
        body_wrap.grid(row=5, column=1, sticky="nsew", pady=6)
        toolbar = tk.Frame(body_wrap, bg=CARD)
        toolbar.pack(fill="x")
        for label, attr, font in STYLE_BUTTONS:
            btn = tk.Label(toolbar, text=label, bg=CARD, fg=GRAY, font=font,
                           width=3, cursor="hand2",
                           highlightbackground="#d4dcea", highlightthickness=1)
            btn.pack(side="left", padx=(0, 4), pady=(0, 4))
            btn.bind("<Button-1>", lambda e, a=attr: self._toggle_font(a))
        lbl_color = tk.Label(toolbar, text="颜色", bg=CARD, fg=ACCENT,
                             font=FONT_UI, cursor="hand2")
        lbl_color.pack(side="left", padx=2)
        lbl_color.bind("<Button-1>", lambda e: self._pick_color())
        lbl_clear = tk.Label(toolbar, text="清除格式", bg=CARD, fg=GRAY,
                             font=FONT_UI, cursor="hand2")
        lbl_clear.pack(side="left", padx=8)
        lbl_clear.bind("<Button-1>", lambda e: self._clear_format())
        self.txt_body = tk.Text(body_wrap, font=FONT_UI, bg=CARD, fg=TEXT,
                                relief="solid", bd=1, wrap="word",
                                height=11, insertbackground=TEXT,
                                undo=True)
        self.txt_body.pack(fill="both", expand=True)
        self.txt_body.insert("1.0", body)
        # 预建全部字体组合标签（避免运行期 tag 优先级竞争）
        for b in (0, 1):
            for i in (0, 1):
                for u in (0, 1):
                    styles = []
                    if b:
                        styles.append("bold")
                    if i:
                        styles.append("italic")
                    if u:
                        styles.append("underline")
                    font = ("Microsoft YaHei UI", 10, *styles) if styles \
                        else ("Microsoft YaHei UI", 10)
                    self.txt_body.tag_configure(
                        richtext.font_tag_name(bool(b), bool(i), bool(u)),
                        font=font)

        # 附件
        row(6, "附件")
        att_bar = ttk.Frame(frm, style="Card.TFrame")
        att_bar.grid(row=6, column=1, sticky="we", pady=6)
        ttk.Button(att_bar, text="添加附件…", command=self._add_attachment
                   ).pack(side="left")
        ttk.Button(att_bar, text="移除选中", command=self._remove_attachment
                   ).pack(side="left", padx=6)
        self.lst_att = tk.Listbox(att_bar, height=3, font=FONT_UI, bg=CARD,
                                  fg=TEXT, relief="solid", bd=1,
                                  selectbackground=ACCENT,
                                  activestyle="none")
        self.lst_att.pack(side="left", fill="x", expand=True, padx=(8, 0))

        # 发送与状态
        btn_bar = ttk.Frame(frm, style="Card.TFrame")
        btn_bar.grid(row=7, column=0, columnspan=2, sticky="e", pady=(10, 0))
        self.var_status = tk.StringVar()
        tk.Label(btn_bar, textvariable=self.var_status, bg=CARD, fg=GRAY,
                 font=FONT_UI).pack(side="left", padx=(0, 10))
        self.btn_send = ttk.Button(btn_bar, text="发送", command=self.send)
        self.btn_send.pack(side="right")

        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(5, weight=1)

    # ---------- 富文本 ----------
    def _sel_range(self) -> tuple[str, str] | None:
        ranges = self.txt_body.tag_ranges("sel")
        if ranges:
            return str(ranges[0]), str(ranges[1])
        return None

    def _toggle_font(self, attr: str):
        """选区加/去粗体、斜体、下划线（按字符逐段处理组合标签）。"""
        sel = self._sel_range()
        if not sel:
            return
        start, end = sel
        attr_idx = {"bold": 0, "italic": 1, "underline": 2}[attr]
        # 判定开或关：选区首字符已有该样式则视为关闭
        cur = richtext.char_flags(self.txt_body, start)
        turn_on = not cur[attr_idx]

        idx = start
        while self.txt_body.compare(idx, "<", end):
            flags = list(richtext.char_flags(self.txt_body, idx))
            flags[attr_idx] = turn_on
            # 清除该字符所有字体标签，再挂新组合
            for t in self.txt_body.tag_names(idx):
                if t.startswith("fb") and len(t) == 7:
                    self.txt_body.tag_remove(t, idx, f"{idx} +1c")
            self.txt_body.tag_add(richtext.font_tag_name(*flags[:3]), idx,
                                  f"{idx} +1c")
            idx = self.txt_body.index(f"{idx} +1c")

    def _pick_color(self):
        sel = self._sel_range()
        if not sel:
            return
        color = colorchooser.askcolor(parent=self.win)
        if not color or not color[1]:
            return
        hexc = color[1]
        tag = richtext.COLOR_PREFIX + hexc
        self.txt_body.tag_configure(tag, foreground=hexc)
        self.txt_body.tag_add(tag, sel[0], sel[1])

    def _clear_format(self):
        sel = self._sel_range()
        if not sel:
            return
        for t in self.txt_body.tag_names(sel[0]):
            if (t.startswith("fb") and len(t) == 7) or \
               t.startswith(richtext.COLOR_PREFIX):
                self.txt_body.tag_remove(t, sel[0], sel[1])

    def _has_style(self) -> bool:
        """是否还残留任何样式标签（须检查标签是否有实际字符范围）。"""
        for t in self.txt_body.tag_names():
            style_tag = t.startswith(richtext.COLOR_PREFIX) or \
                (t.startswith("fb") and len(t) == 7 and t != "fb0i0u0")
            if style_tag and self.txt_body.tag_ranges(t):
                return True
        return False

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
            raise ValueError(f"地址格式有误：{', '.join(bad)}")
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
            cc = self.parse_addresses(self.var_cc.get()) if self.var_cc.get().strip() else []
            bcc = self.parse_addresses(self.var_bcc.get()) if self.var_bcc.get().strip() else []
        except ValueError as e:
            messagebox.showwarning("一邮通", str(e), parent=self.win)
            return
        if not addrs and not cc and not bcc:
            messagebox.showwarning("一邮通", "请填写收件人", parent=self.win)
            return
        acc = self._accounts[self.cmb_account.current()]
        password = self.manager.password(acc.id)
        subject = self.var_subject.get().strip()
        body = self.txt_body.get("1.0", "end").rstrip("\n")
        files = list(self.attachments)
        html_body = richtext.text_to_html(self.txt_body) if self._has_style() else None

        self._sending = True
        self.btn_send.configure(state="disabled")
        self.var_status.set("正在发送…")

        def _work():
            ok, err = False, ""
            try:
                msg = smtp_client.send_mail(acc, password, addrs, subject,
                                            body, files, cc_addrs=cc,
                                            bcc_addrs=bcc, html_body=html_body)
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
