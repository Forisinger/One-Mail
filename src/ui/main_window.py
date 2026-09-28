# -*- coding: utf-8 -*-
"""主窗口（美化版）：蓝白扁平风格。

- 账户面板：卡片式列表，未读数徽章，点击筛选来源
- 邮件列表：隔行底色、未读加粗高亮、搜索框过滤
- 阅读区：主题/发件人/时间结构化排版
- 程序窗口使用与托盘一致的图标
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from PIL import ImageTk

from core.account import Account, AccountManager
from storage import database as db
from core.scheduler import Scheduler
from . import icon as icon_mod
from .account_dialog import AccountDialog

# ---- 配色（与托盘图标同色系） ----
ACCENT = "#1e64dc"        # 主蓝
ACCENT_DARK = "#173f8f"   # 未读文字
ACCENT_SOFT = "#e3ecfb"   # 选中底色
BG = "#eef1f6"            # 窗口底
CARD = "#ffffff"          # 卡片白
TEXT = "#1f2937"
GRAY = "#6b7280"
ROW_ALT = "#f4f7fc"       # 隔行底色

FONT_UI = ("Microsoft YaHei UI", 10)
FONT_UI_B = ("Microsoft YaHei UI", 10, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 13, "bold")


def _setup_style(root: tk.Tk) -> None:
    style = ttk.Style(root)
    for theme in ("vista", "winnative", "clam"):
        if theme in style.theme_names():
            style.theme_use(theme)
            break
    style.configure(".", font=FONT_UI)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Card.TLabel", background=CARD, foreground=TEXT)
    style.configure("Gray.TLabel", background=BG, foreground=GRAY)
    style.configure("Tool.TButton", padding=(12, 6))
    style.configure(
        "Treeview", rowheight=36, font=FONT_UI,
        background=CARD, fieldbackground=CARD, borderwidth=0,
    )
    style.configure(
        "Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"),
        padding=(8, 10), background="#e8edf6", relief="flat",
    )
    style.map(
        "Treeview",
        background=[("selected", ACCENT)],
        foreground=[("selected", "#ffffff")],
    )
    style.configure("TPanedwindow", background=BG)
    style.configure("Sash", sashthickness=6)


class MainWindow:
    def __init__(self, root: tk.Tk, manager: AccountManager, scheduler: Scheduler):
        self.root = root
        self.manager = manager
        self.scheduler = scheduler
        self._filter_account: str | None = None   # None = 全部账户
        self._search_var = tk.StringVar()
        self._account_rows: list[tuple[tk.Frame, str | None]] = []

        root.title("一邮通 OneMail")
        root.geometry("1060x660")
        root.minsize(800, 500)
        root.configure(background=BG)
        _setup_style(root)
        # 程序图标：与托盘同一套绘制，无文件依赖
        self._appicon = ImageTk.PhotoImage(icon_mod.base_icon())
        root.iconphoto(True, self._appicon)

        self._build_toolbar()
        self._build_panes()
        self._build_statusbar()
        self.refresh_accounts()
        self.refresh_mails()

    # ---------- 工具栏 ----------
    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=(10, 8, 10, 4))
        bar.pack(fill="x")

        for text, cmd in (
            ("⟳ 立即收信", self.fetch_now),
            ("✓ 全部已读", self.mark_all_read),
            ("＋ 添加账户", self.add_account),
            ("✎ 编辑账户", self.edit_account),
            ("－ 删除账户", self.remove_account),
            ("✓ 标记已读", self.mark_selected_read),
        ):
            ttk.Button(bar, text=text, command=cmd,
                       style="Tool.TButton").pack(side="left", padx=(0, 6))

        # 搜索框（右侧）
        search_wrap = tk.Frame(bar, bg=CARD, highlightbackground="#d4dcea",
                               highlightthickness=1)
        search_wrap.pack(side="right", padx=(6, 0))
        tk.Label(search_wrap, text="🔍", bg=CARD, fg=GRAY,
                 font=FONT_UI).pack(side="left", padx=(8, 2), pady=5)
        entry = tk.Entry(search_wrap, textvariable=self._search_var,
                         bd=0, bg=CARD, fg=TEXT, font=FONT_UI, width=22,
                         insertbackground=TEXT)
        entry.pack(side="left", padx=(0, 8), pady=5)
        self._search_var.trace_add("write", lambda *_: self.refresh_mails())

    # ---------- 主体三栏 ----------
    def _build_panes(self):
        pane = ttk.Panedwindow(self.root, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=10, pady=6)

        # 左：账户面板（卡片）
        left_card = ttk.Frame(pane, style="Card.TFrame")
        pane.add(left_card, weight=1)
        ttk.Label(left_card, text="邮箱账户", style="Card.TLabel",
                  font=FONT_UI_B, background=CARD,
                  foreground=TEXT).pack(anchor="w", padx=14, pady=(12, 4))
        self.account_list_frame = tk.Frame(left_card, bg=CARD)
        self.account_list_frame.pack(fill="both", expand=True,
                                     padx=8, pady=(4, 8))

        # 右：邮件列表 + 阅读区
        right = ttk.Panedwindow(pane, orient="vertical")
        pane.add(right, weight=3)

        cols = ("account", "from", "subject", "date")
        frame_top = ttk.Frame(right, style="Card.TFrame")
        self.tree = ttk.Treeview(frame_top, columns=cols, show="headings",
                                 selectmode="browse")
        for cid, text, width, anchor in (
            ("account", "来源", 110, "w"),
            ("from", "发件人", 160, "w"),
            ("subject", "主题", 380, "w"),
            ("date", "时间", 140, "w"),
        ):
            self.tree.heading(cid, text=text)
            self.tree.column(cid, width=width, anchor=anchor,
                             stretch=(cid == "subject"))
        vsb = ttk.Scrollbar(frame_top, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._on_mail_open)
        # 行样式：未读加粗着色 + 隔行底色
        self.tree.tag_configure("unread", font=FONT_UI_B, foreground=ACCENT_DARK)
        self.tree.tag_configure("odd", background=ROW_ALT)
        right.add(frame_top, weight=3)

        # 阅读区（卡片）
        body_card = ttk.Frame(right, style="Card.TFrame")
        self.txt_body = tk.Text(
            body_card, wrap="word", state="disabled", relief="flat",
            padx=16, pady=12, bg=CARD, fg=TEXT, font=FONT_UI, bd=0,
            insertbackground=TEXT,
        )
        # 结构化排版标签
        self.txt_body.tag_configure("subject", font=FONT_TITLE, foreground=TEXT,
                                    spacing3=4)
        self.txt_body.tag_configure("meta", font=FONT_UI, foreground=GRAY)
        self.txt_body.tag_configure("divider", foreground="#e2e8f2")
        self.txt_body.tag_configure("body", font=FONT_UI, foreground=TEXT,
                                    spacing1=2, spacing3=2)
        bsb = ttk.Scrollbar(body_card, orient="vertical",
                            command=self.txt_body.yview)
        self.txt_body.configure(yscrollcommand=bsb.set)
        self.txt_body.pack(side="left", fill="both", expand=True)
        bsb.pack(side="right", fill="y")
        right.add(body_card, weight=2)

    # ---------- 状态栏 ----------
    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=CARD, highlightbackground="#dde3ee",
                       highlightthickness=1)
        bar.pack(fill="x", side="bottom")
        self.var_status = tk.StringVar(value="就绪")
        tk.Label(bar, textvariable=self.var_status, bg=CARD, fg=GRAY,
                 font=("Microsoft YaHei UI", 9), anchor="w", padx=12,
                 pady=5).pack(fill="x")

    # ---------- 数据刷新 ----------
    def refresh_accounts(self):
        """重建账户卡片列表（账户数通常很少，直接重建即可）。"""
        for frame, _ in self._account_rows:
            frame.destroy()
        self._account_rows.clear()

        def _add_row(label: str, account_id: str | None, unread: int, sub: str = ""):
            selected = (account_id or None) == self._filter_account
            row = tk.Frame(self.account_list_frame, bg=ACCENT_SOFT if selected else CARD,
                           cursor="hand2")
            row.pack(fill="x", pady=1)
            inner_l = tk.Frame(row, bg=row["bg"])
            inner_l.pack(side="left", fill="x", expand=True, padx=10, pady=8)
            tk.Label(inner_l, text=label, bg=row["bg"],
                     fg=ACCENT_DARK if selected else TEXT,
                     font=FONT_UI_B if unread else FONT_UI,
                     anchor="w").pack(side="left", fill="x", expand=True)
            if sub:
                tk.Label(inner_l, text=sub, bg=row["bg"], fg=GRAY,
                         font=("Microsoft YaHei UI", 8),
                         anchor="w").pack(side="left", fill="x")
            if unread:
                pill = tk.Label(row, text=str(unread), bg=ACCENT, fg="white",
                                font=("Microsoft YaHei UI", 9, "bold"),
                                padx=7, pady=1)
                pill.pack(side="right", padx=(0, 10), pady=8)
            for w in (row,):
                w.bind("<Button-1>", lambda e, aid=account_id: self._select_account(aid))
            for child in row.winfo_children():
                for w in ([child] + list(child.winfo_children())):
                    w.bind("<Button-1>", lambda e, aid=account_id: self._select_account(aid))
            self._account_rows.append((row, account_id))

        total = db.unread_count()
        _add_row("全部邮件", None, total)
        for acc in self.manager.all():
            n = db.unread_count(acc.id)
            state = "" if acc.enabled else "（已停用）"
            _add_row(acc.name + state, acc.id, n, sub=acc.email)

    def _select_account(self, account_id: str | None):
        self._filter_account = account_id
        self.refresh_accounts()
        self.refresh_mails()

    def refresh_mails(self):
        keyword = self._search_var.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        rows = db.list_mails(self._filter_account)
        for i, row in enumerate(rows):
            acc = self.manager.get(row["account_id"])
            acc_name = acc.name if acc else row["account_id"]
            subj = ("📎 " if row["has_attachment"] else "") + (row["subject"] or "")
            if keyword and keyword not in (subj + (row["from_name"] or "")
                                           + (row["from_addr"] or "")).lower():
                continue
            tags = []
            if not row["is_read"]:
                tags.append("unread")
            if i % 2 == 1:
                tags.append("odd")
            self.tree.insert("", "end", iid=str(row["id"]),
                             values=(acc_name, row["from_name"] or row["from_addr"],
                                     subj, (row["received_at"] or "")[:16]),
                             tags=tuple(tags))

    def full_refresh(self):
        self.refresh_accounts()
        self.refresh_mails()

    # ---------- 交互 ----------
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
        acc_name = acc.name if acc else mail["account_id"]
        body = mail["body_text"] or "（无正文/解析失败）"
        self.txt_body.configure(state="normal")
        self.txt_body.delete("1.0", "end")
        self.txt_body.insert("end", mail["subject"] or "(无主题)", "subject")
        self.txt_body.insert("end", "\n")
        self.txt_body.insert("end",
                             f"来自 {mail['from_name']} <{mail['from_addr']}>"
                             f"　·　{mail['received_at']}"
                             f"　·　来源：{acc_name}\n", "meta")
        self.txt_body.insert("end", "─" * 60 + "\n\n", "divider")
        self.txt_body.insert("end", body, "body")
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
        if self._filter_account is None:
            return None
        return self.manager.get(self._filter_account)

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
