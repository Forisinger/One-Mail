# -*- coding: utf-8 -*-
"""主窗口（美化版）：蓝白扁平风格。

- 账户面板：卡片式列表，未读数徽章，点击筛选来源
- 邮件列表：隔行底色、未读加粗高亮、搜索框过滤
- 阅读区：主题/发件人/时间结构化排版
- 程序窗口使用与托盘一致的图标
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import ImageTk

from core.account import Account, AccountManager
from storage import database as db
from storage import config as config_store
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
        self._filter_var = tk.StringVar(value="全部")
        self._sort_key = "date"      # 列头排序（v1.5.2）
        self._sort_desc = True
        self._col_titles = {}
        self._current_mail = None    # 阅读区当前邮件（保存附件用）
        self._account_status: dict[str, str] = {}   # 账户最近连接状态（v1.6.2）
        self._account_rows: list[tuple[tk.Frame, str | None]] = []
        self._collapsed = bool(
            config_store.load().get("settings", {}).get("accounts_collapsed", False)
        )

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
            ("✉ 写邮件", self.compose_new),
            ("↩ 回复", self.compose_reply),
            ("✓ 全部已读", self.mark_all_read),
            ("＋ 添加账户", self.add_account),
            ("✎ 编辑账户", self.edit_account),
            ("－ 删除账户", self.remove_account),
            ("✓ 标记已读", self.mark_selected_read),
        ):
            ttk.Button(bar, text=text, command=cmd,
                       style="Tool.TButton").pack(side="left", padx=(0, 6))

        # 过滤器（搜索框左侧）：全部 / 只看未读 / 有附件
        self._filter_box = ttk.Combobox(
            bar, textvariable=self._filter_var, width=10, state="readonly",
            values=("全部", "只看未读", "有附件"),
        )
        self._filter_box.pack(side="right", padx=(6, 0))
        self._filter_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_mails())

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
        # 搜索防抖：停顿 300ms 后才查库，避免每敲一个字符全表扫描
        self._search_job = None
        self._search_var.trace_add("write", self._on_search_changed)

    # ---------- 主体三栏 ----------
    def _build_panes(self):
        # 最左：收起/展开账户面板的细条（面板收起后仍可由此展开）
        strip = tk.Frame(self.root, bg=BG)
        strip.pack(side="left", fill="y", padx=(10, 0), pady=6)
        self._strip_btn = tk.Label(
            strip, text="«", bg=CARD, fg=GRAY, font=FONT_UI_B, width=2,
            cursor="hand2", highlightbackground="#d4dcea", highlightthickness=1,
        )
        self._strip_btn.pack(expand=True, fill="y")
        self._strip_btn.bind("<Button-1>", lambda e: self.toggle_accounts())

        self._pane = ttk.Panedwindow(self.root, orient="horizontal")
        self._pane.pack(fill="both", expand=True, padx=(6, 10), pady=6)

        # 左：账户面板（卡片）
        self._left_card = ttk.Frame(self._pane, style="Card.TFrame")
        self._pane.insert("end", self._left_card, weight=1)
        header = tk.Frame(self._left_card, bg=CARD)
        header.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(header, text="邮箱账户", bg=CARD, fg=TEXT,
                 font=FONT_UI_B).pack(side="left")
        self._header_btn = tk.Label(header, text="«", bg=CARD, fg=GRAY,
                                    font=FONT_UI_B, cursor="hand2")
        self._header_btn.pack(side="right")
        self._header_btn.bind("<Button-1>", lambda e: self.toggle_accounts())
        self.account_list_frame = tk.Frame(self._left_card, bg=CARD)
        self.account_list_frame.pack(fill="both", expand=True,
                                     padx=8, pady=(4, 8))

        # 右：邮件列表 + 阅读区
        right = ttk.Panedwindow(self._pane, orient="vertical")
        self._pane.add(right, weight=3)

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
            self._col_titles[cid] = text
            self.tree.heading(cid, text=text,
                              command=lambda c=cid: self._on_sort(c))
            self.tree.column(cid, width=width, anchor=anchor,
                             stretch=(cid == "subject"))
        vsb = ttk.Scrollbar(frame_top, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._on_mail_open)
        self.tree.bind("<Button-3>", self._mail_list_menu)
        self.tree.bind("<Delete>", lambda e: self.delete_selected_mail())
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
        self.txt_body.bind("<Button-3>", self._body_menu)
        right.add(body_card, weight=2)

        # 应用上次记忆的收起状态
        if self._collapsed:
            self.toggle_accounts()

    # ---------- 账户面板收起/展开 ----------
    def toggle_accounts(self):
        """收起或展开左侧账户面板（含"全部邮件"），状态写入配置记忆。"""
        self._collapsed = not self._collapsed
        if self._collapsed:
            self._pane.remove(self._left_card)
        else:
            self._pane.insert(0, self._left_card, weight=1)
        chevron = "»" if self._collapsed else "«"
        self._strip_btn.configure(text=chevron)
        self._header_btn.configure(text=chevron)
        try:
            cfg = config_store.load()
            cfg.setdefault("settings", {})["accounts_collapsed"] = self._collapsed
            config_store.save(cfg)
        except Exception:
            pass  # 状态记忆失败不影响功能

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
    def _on_sort(self, cid: str):
        """点击列头排序：再次点击同列反转方向，列头带 ▲/▼ 指示。"""
        if self._sort_key == cid:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_key, self._sort_desc = cid, False
        for c, base in self._col_titles.items():
            mark = ""
            if c == self._sort_key:
                mark = " ▼" if self._sort_desc else " ▲"
            self.tree.heading(c, text=base + mark)
        self.refresh_mails()

    def _sort_rows(self, rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
        key = self._sort_key
        desc = self._sort_desc

        def sort_value(r):
            if key == "account":
                acc = self.manager.get(r["account_id"])
                return (acc.name if acc else r["account_id"]).lower()
            if key == "from":
                return (r["from_name"] or r["from_addr"] or "").lower()
            if key == "subject":
                return (r["subject"] or "").lower()
            return r["received_at"] or ""   # date：ISO 字符串可直接比较

        return sorted(rows, key=sort_value, reverse=desc)

    def _on_search_changed(self, *_):
        if self._search_job is not None:
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(300, self._search_fire)

    def _search_fire(self):
        self._search_job = None
        self.refresh_mails()

    def set_account_status(self, account_id: str, text: str):
        """记录账户最近状态并刷新对应卡片（连接/推送/异常等）。"""
        if self._account_status.get(account_id) == text:
            return
        self._account_status[account_id] = text
        self.refresh_accounts()

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
                w.bind("<Button-3>", lambda e, aid=account_id: self._account_menu(aid, e))
            for child in row.winfo_children():
                for w in ([child] + list(child.winfo_children())):
                    w.bind("<Button-1>", lambda e, aid=account_id: self._select_account(aid))
                    w.bind("<Button-3>", lambda e, aid=account_id: self._account_menu(aid, e))
            self._account_rows.append((row, account_id))

        total = db.unread_count()
        _add_row("全部邮件", None, total)
        for acc in self.manager.all():
            n = db.unread_count(acc.id)
            state = "" if acc.enabled else "（已停用）"
            status = self._account_status.get(acc.id, "")
            sub = acc.email + (f"　·　{status}" if status else "")
            _add_row(acc.name + state, acc.id, n, sub=sub)

    def _select_account(self, account_id: str | None):
        self._filter_account = account_id
        self.refresh_accounts()
        self.refresh_mails()

    def refresh_mails(self):
        """按账户 + 过滤器 + 关键字组合查询（搜索下沉 SQL，正文也会被检索）。"""
        keyword = self._search_var.get().strip()
        mode = self._filter_var.get()
        self.tree.delete(*self.tree.get_children())
        rows, total = db.search_mails(
            self._filter_account, keyword,
            unread_only=(mode == "只看未读"),
            has_attach=(mode == "有附件"),
        )
        rows = self._sort_rows(rows)
        for i, row in enumerate(rows):
            acc = self.manager.get(row["account_id"])
            acc_name = acc.name if acc else row["account_id"]
            subj = ("📎 " if row["has_attachment"] else "") + (row["subject"] or "")
            tags = []
            if not row["is_read"]:
                tags.append("unread")
            if i % 2 == 1:
                tags.append("odd")
            self.tree.insert("", "end", iid=str(row["id"]),
                             values=(acc_name, row["from_name"] or row["from_addr"],
                                     subj, (row["received_at"] or "")[:16]),
                             tags=tuple(tags))
        filtered = len(rows)
        self.var_status.set(
            f"共 {total} 封，显示 {filtered} 封"
            if (keyword or mode != "全部") else f"共 {total} 封")

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
        self._current_mail = mail
        body = mail["body_text"] or "（无正文/解析失败）"
        self.txt_body.configure(state="normal")
        self.txt_body.delete("1.0", "end")
        self.txt_body.insert("end", mail["subject"] or "(无主题)", "subject")
        self.txt_body.insert("end", "\n")
        self.txt_body.insert("end",
                             f"来自 {mail['from_name']} <{mail['from_addr']}>"
                             f"　·　{mail['received_at']}"
                             f"　·　来源：{acc_name}\n", "meta")
        try:
            att_names = json.loads(mail["attachment_names"]) \
                if mail["attachment_names"] else []
        except (json.JSONDecodeError, TypeError):
            att_names = []
        if att_names:
            self.txt_body.insert("end", f"📎 附件：{'、'.join(att_names)}\n", "meta")
        self.txt_body.insert("end", "─" * 60 + "\n\n", "divider")
        self.txt_body.insert("end", body, "body")
        self.txt_body.configure(state="disabled")

    # ---------- 复制与右键菜单 ----------
    def _copy_to_clipboard(self, text: str, label: str = "内容"):
        text = (text or "").strip()
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        preview = text if len(text) <= 24 else text[:24] + "…"
        self.var_status.set(f"已复制{label}：{preview}")

    def _mail_list_menu(self, event):
        """邮件列表右键：复制主题/发件人/邮箱地址/正文 + 删除。"""
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        mail = db.get_mail(int(row))
        if mail is None:
            return
        menu = tk.Menu(self.root, tearoff=0)
        subj = mail["subject"] or ""
        name = mail["from_name"] or ""
        addr = mail["from_addr"] or ""
        for label, val in (
            ("复制主题", subj),
            ("复制发件人", name),
            ("复制发件人邮箱", addr),
            ("复制正文", mail["body_text"] or ""),
        ):
            menu.add_command(label=label, state="normal" if val.strip() else "disabled",
                             command=lambda v=val, l=label[2:]: self._copy_to_clipboard(v, l))
        menu.add_separator()
        menu.add_command(label="删除（仅本地缓存）", command=self.delete_selected_mail)
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()          # 现代 tkinter 通常自动释放，兜底
        menu.destroy()               # 用完即毁，托盘长年运行不累积死控件

    def delete_selected_mail(self):
        """删除选中邮件的本地缓存（不动服务器上的邮件）。"""
        sel = self.tree.selection()
        if not sel:
            return
        mail_id = int(sel[0])
        db.delete_mail(mail_id)
        if self._current_mail and self._current_mail["id"] == mail_id:
            self._current_mail = None
            self.txt_body.configure(state="normal")
            self.txt_body.delete("1.0", "end")
            self.txt_body.configure(state="disabled")
        self.refresh_mails()
        self.refresh_accounts()
        self.var_status.set("已从本地缓存删除该邮件（服务器不受影响）")

    def _account_menu(self, account_id: str | None, event):
        """账户面板右键：复制邮箱地址/账户名。"""
        if not account_id:
            return  # "全部邮件"卡片无地址可复制
        acc = self.manager.get(account_id)
        if acc is None:
            return
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="复制邮箱地址", command=lambda: self._copy_to_clipboard(acc.email, "邮箱地址"))
        menu.add_command(label="复制账户名", command=lambda: self._copy_to_clipboard(acc.name, "账户名"))
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()
        menu.destroy()

    def _body_menu(self, event):
        """阅读区右键：复制选中 / 全选 / 保存附件。"""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="复制", command=self._copy_body_selection)
        menu.add_command(label="全选", command=lambda: self.txt_body.tag_add("sel", "1.0", "end"))
        has_att = bool(self._current_mail and self._current_mail["has_attachment"])
        menu.add_separator()
        menu.add_command(label="保存附件…", state="normal" if has_att else "disabled",
                         command=self.save_attachments)
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()
        menu.destroy()

    def save_attachments(self):
        """把当前邮件的附件保存到所选目录（按 UID 从服务器重新取原文）。"""
        from core.mail_client import MailClient
        from core.parser import extract_attachments
        mail = self._current_mail
        if not mail or not mail["has_attachment"]:
            return
        acc = self.manager.get(mail["account_id"])
        if acc is None:
            self.var_status.set("该邮件的来源账户已被删除，无法取回附件")
            return
        dest = filedialog.askdirectory(parent=self.root, title="选择附件保存位置")
        if not dest:
            return
        pwd = self.manager.password(acc.id)
        # 邮件行自带来源文件夹：账户后来改过收信文件夹时，
        # 用 acc.folder 会在错误的文件夹里按 UID 取到另一封邮件
        uid, folder = mail["uid"], (mail["folder"] or getattr(acc, "folder", "INBOX"))
        self.var_status.set("正在从服务器取回邮件原文…")

        def work():
            try:
                raw = MailClient.fetch_raw(acc, pwd, folder, uid)
                atts = extract_attachments(raw)
                if not atts:
                    msg = "未在服务器原文中解析出附件"
                else:
                    saved = 0
                    reserved = {"CON", "PRN", "AUX", "NUL"} | {
                        f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}
                    for name, data in atts:
                        safe = os.path.basename(name.replace("\\", "_")) or "附件"
                        if os.path.splitext(safe)[0].upper() in reserved:
                            safe += "_"   # Windows 保留设备名（con/nul/...）不可作文件名
                        path = os.path.join(dest, safe)
                        stem, ext = os.path.splitext(path)
                        n = 1
                        while os.path.exists(path):
                            path = f"{stem}({n}){ext}"
                            n += 1
                        with open(path, "wb") as f:
                            f.write(data)
                        saved += 1
                    msg = f"已保存 {saved} 个附件到 {dest}"
            except Exception as e:
                msg = f"附件保存失败：{type(e).__name__}: {e}"
            self.root.after(0, lambda: self.var_status.set(msg))

        threading.Thread(target=work, name="onemail-attach", daemon=True).start()

    def _copy_body_selection(self):
        try:
            text = self.txt_body.get("sel.first", "sel.last")
        except tk.TclError:
            text = ""
        self._copy_to_clipboard(text, "选中内容")

    def fetch_now(self):
        n = 0
        for acc in self.manager.enabled():
            client = self.scheduler.client(acc.id)
            if client is not None and not client.stopped:
                client.wake()   # 真正打断 IDLE 等待/轮询睡眠，立即抓一次
                n += 1
        self.var_status.set(f"已请求 {n} 个账户立即收信")

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

    # ---------- 写信 ----------
    def compose_new(self):
        from .compose_window import ComposeWindow
        acc = self._selected_account()
        ComposeWindow(self.root, self.manager, account=acc)

    def compose_reply(self):
        """回复选中的邮件：预填收件人/主题/引用头。"""
        from .compose_window import ComposeWindow
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("一邮通", "请先选中要回复的邮件")
            return
        mail = db.get_mail(int(sel[0]))
        if mail is None:
            return
        acc = self.manager.get(mail["account_id"])
        reply_to = mail["from_addr"] or ""
        subj = mail["subject"] or ""
        if subj and not subj.startswith(("回复：", "回复:", "Re:", "Re:")):
            subj = f"回复：{subj}"
        quote = (f"\n\n-------- 原始邮件 --------\n"
                 f"发件人：{mail['from_name'] or reply_to} <{reply_to}>\n"
                 f"时间：{mail['received_at']}\n"
                 f"主题：{mail['subject'] or ''}\n\n"
                 f"{mail['body_text'] or ''}\n")
        ComposeWindow(self.root, self.manager, account=acc, to=reply_to,
                      subject=subj, body=quote)

    def edit_account(self):
        acc = self._selected_account()
        if acc is None:
            messagebox.showinfo("一邮通", "请先在左侧列表选中要编辑的账户")
            return
        AccountDialog(self.root, self.manager, account=acc,
                      on_saved=lambda a, p: self._on_account_saved(a, p))

    def prompt_missing_password(self):
        """启动时若有账户缺密码，自动弹出编辑框录入授权码（保存后继续下一个）。"""
        for acc in self.manager.all():
            if acc.enabled and not self.manager.password(acc.id):
                self.var_status.set(f"账户 {acc.name} 缺少授权码，请输入")

                def _after_saved(a, p):
                    self._on_account_saved(a, p)
                    self.prompt_missing_password()   # 链式处理剩余缺码账户
                AccountDialog(self.root, self.manager, account=acc,
                              on_saved=_after_saved)
                return  # 模态对话框一次只能弹一个

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
        self._account_status.pop(acc.id, None)
        self._filter_account = None
        self.full_refresh()
        self.root.event_generate("<<UnreadChanged>>", when="tail")

    def set_status(self, text: str):
        self.var_status.set(text)
