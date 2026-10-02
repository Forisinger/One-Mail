# -*- coding: utf-8 -*-
"""主窗口：蓝白扁平风格（v1.9.0 起配色/语言/主题可配置）。

- 账户面板：卡片式列表，未读数徽章，点击筛选来源；底部本地文件夹分区
- 邮件列表：隔行底色、未读加粗高亮、搜索框过滤、可移动到本地文件夹
- 阅读区：主题/发件人/时间结构化排版；HTML 邮件走富文本渲染（htmltext）
- 附件：右键逐个「打开 / 另存为…」或「全部保存到…」（按需从服务器取原文）
- AI：阅读区右键 / 工具栏「AI 总结」（OpenAI 兼容接口，后台线程请求）
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from PIL import ImageTk

from core.account import Account, AccountManager
from core.flag_sync import FlagSync
from storage import database as db
from storage import config as config_store
from core.scheduler import Scheduler
from . import i18n
from . import theme as theme_mod
from . import icon as icon_mod
from .account_dialog import AccountDialog
from .htmltext import render_html

FONT_UI = ("Microsoft YaHei UI", 10)
FONT_UI_B = ("Microsoft YaHei UI", 10, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 13, "bold")


def _setup_style(root: tk.Tk, c: dict[str, str]) -> None:
    style = ttk.Style(root)
    for theme in ("vista", "winnative", "clam"):
        if theme in style.theme_names():
            style.theme_use(theme)
            break
    style.configure(".", font=FONT_UI)
    style.configure("TFrame", background=c["BG"])
    style.configure("Card.TFrame", background=c["CARD"])
    style.configure("TLabel", background=c["BG"], foreground=c["TEXT"])
    style.configure("Card.TLabel", background=c["CARD"], foreground=c["TEXT"])
    style.configure("Gray.TLabel", background=c["BG"], foreground=c["GRAY"])
    style.configure("Tool.TButton", padding=(12, 6))
    style.configure(
        "Treeview", rowheight=36, font=FONT_UI,
        background=c["CARD"], fieldbackground=c["CARD"], borderwidth=0,
        foreground=c["TEXT"],
    )
    style.configure(
        "Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"),
        padding=(8, 10), background=c["HEADING"], relief="flat",
        foreground=c["TEXT"],
    )
    style.map(
        "Treeview",
        background=[("selected", c["ACCENT"])],
        foreground=[("selected", c["SEL_FG"])],
    )
    style.configure("TPanedwindow", background=c["BG"])
    style.configure("Sash", sashthickness=6)


def _tr_status(text: str) -> str:
    """core 线程的状态文案按当前语言显示：先整句查表，再兜底正则拼装。"""
    if not text:
        return text
    tr = i18n.t(text)
    if tr != text:
        return tr
    m = re.match(r"连接异常：(.+?)，(\d+)s 后重连", text)
    if m:
        return (i18n.t("连接异常：{err}").format(err=m.group(1))
                + ", " + i18n.t("{n}s 后重连").format(n=m.group(2)))
    return text


class MainWindow:
    def __init__(self, root: tk.Tk, manager: AccountManager, scheduler: Scheduler,
                 flag_sync: FlagSync | None = None):
        self.root = root
        self.manager = manager
        self.scheduler = scheduler
        self.flag_sync = flag_sync   # 已读状态同步（v1.7.0），None = 不同步
        self.C = theme_mod.colors()   # 当前主题调色板（v1.9.0）
        self._filter_account: str | None = None   # None = 全部账户
        self._filter_local: str | None = None     # None=全部；''=收件箱；其他=文件夹
        self._search_var = tk.StringVar()
        self._filter_var = tk.StringVar(value=i18n.t("全部"))
        self._sort_key = "date"      # 列头排序（v1.5.2）
        self._sort_desc = True
        self._col_titles = {}
        self._current_mail = None    # 阅读区当前邮件（附件/AI 总结用）
        self._account_status: dict[str, str] = {}   # 账户最近连接状态（v1.6.2）
        self._account_rows: list[tuple[tk.Frame, str | None]] = []
        self._folder_rows: list[tk.Frame] = []
        self._collapsed = bool(
            config_store.load().get("settings", {}).get("accounts_collapsed", False)
        )

        root.title(i18n.t("一邮通 OneMail"))
        root.geometry("1060x660")
        root.minsize(800, 500)
        root.configure(background=self.C["BG"])
        _setup_style(root, self.C)
        # 程序图标：与托盘同一套绘制，无文件依赖
        self._appicon = ImageTk.PhotoImage(icon_mod.base_icon())
        root.iconphoto(True, self._appicon)

        self._build_toolbar()
        self._build_panes()
        self._build_statusbar()
        self.refresh_accounts()
        self.refresh_mails()

    # ---------- 配置小助手 ----------
    def _get_folders(self) -> list[str]:
        try:
            return list(config_store.load().get("settings", {})
                        .get("local_folders", []))
        except Exception:
            return []

    def _set_folders(self, folders: list[str]) -> None:
        try:
            cfg = config_store.load()
            cfg.setdefault("settings", {})["local_folders"] = folders
            config_store.save(cfg)
        except Exception:
            pass

    def _ai_conf(self) -> tuple[str, str, str]:
        """返回 (base_url, model, key)。key 经 DPAPI 解密。"""
        try:
            ai = config_store.load().get("settings", {}).get("ai", {})
        except Exception:
            ai = {}
        from core import security
        return (ai.get("base_url", ""), ai.get("model", ""),
                security.load_password("__ai__"))

    # ---------- 工具栏 ----------
    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=(10, 8, 10, 4))
        bar.pack(fill="x")

        for text, cmd in (
            (i18n.t("⚙ 设置"), self.open_settings),   # 左上角齿轮（v1.10.0 应晨央要求前置）
            (i18n.t("⟳ 立即收信"), self.fetch_now),
            (i18n.t("✉ 写邮件"), self.compose_new),
            (i18n.t("↩ 回复"), self.compose_reply),
            (i18n.t("✓ 全部已读"), self.mark_all_read),
            (i18n.t("＋ 添加账户"), self.add_account),
            (i18n.t("✎ 编辑账户"), self.edit_account),
            (i18n.t("－ 删除账户"), self.remove_account),
            (i18n.t("✓ 标记已读"), self.mark_selected_read),
            (i18n.t("🤖 AI 总结"), self.ai_summary),
        ):
            ttk.Button(bar, text=text, command=cmd,
                       style="Tool.TButton").pack(side="left", padx=(0, 6))

        # 过滤器（搜索框左侧）：全部 / 只看未读 / 有附件
        self._filter_values = (i18n.t("全部"), i18n.t("只看未读"),
                               i18n.t("有附件"))
        self._filter_box = ttk.Combobox(
            bar, textvariable=self._filter_var, width=10, state="readonly",
            values=self._filter_values,
        )
        self._filter_box.pack(side="right", padx=(6, 0))
        self._filter_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_mails())

        # 搜索框（右侧）
        search_wrap = tk.Frame(bar, bg=self.C["CARD"],
                               highlightbackground=self.C["BORDER"],
                               highlightthickness=1)
        search_wrap.pack(side="right", padx=(6, 0))
        tk.Label(search_wrap, text="🔍", bg=self.C["CARD"], fg=self.C["GRAY"],
                 font=FONT_UI).pack(side="left", padx=(8, 2), pady=5)
        entry = tk.Entry(search_wrap, textvariable=self._search_var,
                         bd=0, bg=self.C["CARD"], fg=self.C["TEXT"],
                         font=FONT_UI, width=22,
                         insertbackground=self.C["TEXT"])
        entry.pack(side="left", padx=(0, 8), pady=5)
        entry.bind("<Escape>", lambda e: self._search_var.set(""))  # Esc 清空搜索
        # 搜索防抖：停顿 300ms 后才查库，避免每敲一个字符全表扫描
        self._search_job = None
        self._search_var.trace_add("write", self._on_search_changed)

    def open_settings(self):
        from .settings_dialog import SettingsDialog
        SettingsDialog(self.root)

    # ---------- 主体三栏 ----------
    def _build_panes(self):
        # 最左：收起/展开账户面板的细条（面板收起后仍可由此展开）
        strip = tk.Frame(self.root, bg=self.C["BG"])
        strip.pack(side="left", fill="y", padx=(10, 0), pady=6)
        self._strip_btn = tk.Label(
            strip, text="«", bg=self.C["CARD"], fg=self.C["GRAY"],
            font=FONT_UI_B, width=2, cursor="hand2",
            highlightbackground=self.C["BORDER"], highlightthickness=1,
        )
        self._strip_btn.pack(expand=True, fill="y")
        self._strip_btn.bind("<Button-1>", lambda e: self.toggle_accounts())

        self._pane = ttk.Panedwindow(self.root, orient="horizontal")
        self._pane.pack(fill="both", expand=True, padx=(6, 10), pady=6)

        # 左：账户面板（卡片）
        self._left_card = ttk.Frame(self._pane, style="Card.TFrame")
        self._pane.insert("end", self._left_card, weight=1)
        header = tk.Frame(self._left_card, bg=self.C["CARD"])
        header.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(header, text=i18n.t("邮箱账户"), bg=self.C["CARD"],
                 fg=self.C["TEXT"], font=FONT_UI_B).pack(side="left")
        self._header_btn = tk.Label(header, text="«", bg=self.C["CARD"],
                                    fg=self.C["GRAY"], font=FONT_UI_B,
                                    cursor="hand2")
        self._header_btn.pack(side="right")
        self._header_btn.bind("<Button-1>", lambda e: self.toggle_accounts())
        self.account_list_frame = tk.Frame(self._left_card, bg=self.C["CARD"])
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
            ("account", i18n.t("来源"), 110, "w"),
            ("from", i18n.t("发件人"), 160, "w"),
            ("subject", i18n.t("主题"), 380, "w"),
            ("date", i18n.t("时间"), 140, "w"),
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
        self.tree.bind("<Return>", self._on_mail_open)   # 键盘用户也能打开邮件
        self.tree.bind("<Button-3>", self._mail_list_menu)
        self.tree.bind("<Delete>", lambda e: self.delete_selected_mail())
        # 行样式：未读加粗着色 + 隔行底色
        self.tree.tag_configure("unread", font=FONT_UI_B,
                                foreground=self.C["ACCENT_DARK"])
        self.tree.tag_configure("odd", background=self.C["ROW_ALT"])
        right.add(frame_top, weight=3)

        # 阅读区（卡片）
        body_card = ttk.Frame(right, style="Card.TFrame")
        self.txt_body = tk.Text(
            body_card, wrap="word", state="disabled", relief="flat",
            padx=16, pady=12, bg=self.C["CARD"], fg=self.C["TEXT"],
            font=FONT_UI, bd=0, insertbackground=self.C["TEXT"],
        )
        # 结构化排版标签
        self.txt_body.tag_configure("subject", font=FONT_TITLE,
                                    foreground=self.C["TEXT"], spacing3=4)
        self.txt_body.tag_configure("meta", font=FONT_UI,
                                    foreground=self.C["GRAY"])
        self.txt_body.tag_configure("divider", foreground=self.C["DIVIDER"])
        self.txt_body.tag_configure("body", font=FONT_UI,
                                    foreground=self.C["TEXT"],
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
        bar = tk.Frame(self.root, bg=self.C["CARD"],
                       highlightbackground=self.C["DIVIDER"],
                       highlightthickness=1)
        bar.pack(fill="x", side="bottom")
        self.var_status = tk.StringVar(value=i18n.t("就绪"))
        tk.Label(bar, textvariable=self.var_status, bg=self.C["CARD"],
                 fg=self.C["GRAY"], font=("Microsoft YaHei UI", 9),
                 anchor="w", padx=12, pady=5).pack(fill="x")

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
        text = _tr_status(text)
        if self._account_status.get(account_id) == text:
            return
        self._account_status[account_id] = text
        self.refresh_accounts()

    def refresh_accounts(self):
        """重建账户卡片列表（账户数通常很少，直接重建即可）。"""
        for frame, _ in self._account_rows:
            frame.destroy()
        for frame in self._folder_rows:
            frame.destroy()
        self._account_rows.clear()
        self._folder_rows.clear()

        def _add_row(label: str, account_id: str | None, unread: int,
                     sub: str = "", selected: bool = False,
                     text_color: str | None = None,
                     sub_color: str | None = None):
            row = tk.Frame(self.account_list_frame,
                           bg=self.C["ACCENT_SOFT"] if selected else self.C["CARD"],
                           cursor="hand2")
            row.pack(fill="x", pady=1)
            inner_l = tk.Frame(row, bg=row["bg"])
            inner_l.pack(side="left", fill="x", expand=True, padx=10, pady=8)
            tk.Label(inner_l, text=label, bg=row["bg"],
                     fg=text_color or (self.C["ACCENT_DARK"] if selected else self.C["TEXT"]),
                     font=FONT_UI_B if unread else FONT_UI,
                     anchor="w").pack(side="left", fill="x", expand=True)
            if sub:
                tk.Label(inner_l, text=sub, bg=row["bg"],
                         fg=sub_color or self.C["GRAY"],
                         font=("Microsoft YaHei UI", 8),
                         anchor="w").pack(side="left", fill="x")
            if unread:
                pill = tk.Label(row, text=str(unread), bg=self.C["ACCENT"],
                                fg=self.C["SEL_FG"],
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
            return row

        total = db.unread_count()
        _add_row(i18n.t("全部邮件"), None, total)
        for acc in self.manager.all():
            n = db.unread_count(acc.id)
            state = "" if acc.enabled else i18n.t("（已停用）")
            status = self._account_status.get(acc.id, "")
            sub = acc.email + (f"　·　{status}" if status else "")
            if self._is_error_status(status):
                # 异常账户红色高亮，多账户时一眼定位（v1.10.2）
                _add_row(acc.name + state, acc.id, n, sub=sub,
                         sub_color=self.C["ERR"])
            else:
                _add_row(acc.name + state, acc.id, n, sub=sub)

        # ---- 本地文件夹分区（v1.9.0） ----
        counts = db.local_folder_counts()
        folders = self._get_folders()
        sep = tk.Frame(self.account_list_frame, bg=self.C["CARD"], height=8)
        sep.pack(fill="x")
        self._folder_rows.append(sep)
        head = tk.Frame(self.account_list_frame, bg=self.C["CARD"])
        head.pack(fill="x", padx=10, pady=(0, 2))
        tk.Label(head, text=i18n.t("文件夹"), bg=self.C["CARD"],
                 fg=self.C["GRAY"], font=("Microsoft YaHei UI", 9, "bold"),
                 anchor="w").pack(side="left")
        head.bind("<Button-3>", lambda e: self._folder_menu(e, None))
        self._folder_rows.append(head)
        inbox_c, inbox_u = counts.get("", (0, 0))
        self._add_folder_row(i18n.t("收件箱"), "", inbox_u, selected=(
            self._filter_local == ""))
        for name in folders:
            c, u = counts.get(name, (0, 0))
            self._add_folder_row(name, name, u,
                                 selected=(self._filter_local == name))

    def _add_folder_row(self, label: str, key: str, unread: int,
                        selected: bool = False):
        row = tk.Frame(self.account_list_frame,
                       bg=self.C["ACCENT_SOFT"] if selected else self.C["CARD"],
                       cursor="hand2")
        row.pack(fill="x", pady=1)
        tk.Label(row, text=("📁 " if key else "📥 ") + label, bg=row["bg"],
                 fg=self.C["ACCENT_DARK"] if selected else self.C["TEXT"],
                 font=FONT_UI_B if unread else FONT_UI,
                 anchor="w").pack(side="left", fill="x", expand=True,
                                  padx=10, pady=6)
        if unread:
            pill = tk.Label(row, text=str(unread), bg=self.C["ACCENT"],
                            fg=self.C["SEL_FG"],
                            font=("Microsoft YaHei UI", 9, "bold"),
                            padx=7, pady=1)
            pill.pack(side="right", padx=(0, 10), pady=6)
        row.bind("<Button-1>", lambda e, k=key: self._select_folder(k))
        row.bind("<Button-3>", lambda e, k=key: self._folder_menu(e, k or None))
        self._folder_rows.append(row)

    def _select_folder(self, key: str):
        # 再点一次同一文件夹 = 取消筛选（回到全部）
        self._filter_local = None if self._filter_local == key else key
        self.refresh_accounts()
        self.refresh_mails()

    def _folder_menu(self, event, name: str | None):
        """文件夹分区右键：新建 / 删除文件夹。"""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=i18n.t("新建文件夹…"),
                         command=self.create_folder)
        if name:
            menu.add_command(label=i18n.t("删除文件夹"),
                             command=lambda: self.delete_folder(name))
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()
        menu.destroy()

    def create_folder(self):
        name = simpledialog.askstring(
            i18n.t("新建文件夹"), i18n.t("文件夹名称："), parent=self.root)
        name = (name or "").strip()
        if not name:
            return
        folders = self._get_folders()
        if name in folders or name == "":
            self.var_status.set(i18n.t("文件夹已存在"))
            return
        folders.append(name)
        self._set_folders(folders)
        self.refresh_accounts()

    def delete_folder(self, name: str):
        if not messagebox.askyesno(
                i18n.t("一邮通"),
                i18n.t("删除文件夹 {name}？其中邮件将移回收件箱。").format(name=name),
                parent=self.root):
            return
        folders = self._get_folders()
        if name in folders:
            folders.remove(name)
            self._set_folders(folders)
        db.empty_local_folder(name)
        if self._filter_local == name:
            self._filter_local = None
        self.refresh_accounts()
        self.refresh_mails()

    def _move_selected_to(self, local_folder: str):
        sel = self.tree.selection()
        if not sel:
            return
        n = db.move_mails_to_folder([int(s) for s in sel], local_folder)
        target = i18n.t("收件箱") if local_folder == "" else local_folder
        self.var_status.set(
            i18n.t("移动成功：{n} 封 → {folder}").format(n=n, folder=target))
        self.refresh_accounts()
        self.refresh_mails()

    def _select_account(self, account_id: str | None):
        self._filter_account = account_id
        self.refresh_accounts()
        self.refresh_mails()

    @staticmethod
    def _friendly_date(iso: str) -> str:
        """人性化时间列：今天只显时分，今年显月日+时分，跨年带年份。"""
        if not iso:
            return ""
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(iso)
            today = datetime.now().date()
            if dt.date() == today:
                return dt.strftime("%H:%M")
            if dt.date().year == today.year:
                return dt.strftime("%m-%d %H:%M")
            return dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return iso[:16]

    @staticmethod
    def _is_error_status(text: str) -> bool:
        """账户状态是否为异常（红色高亮用，v1.10.2）。"""
        return any(k in (text or "") for k in
                   ("异常", "失败", "重新登录", "已失效", "未设置密码"))

    @staticmethod
    def _friendly_error(e) -> str:
        """常见网络异常 → 人话（未命中回退原格式，v1.10.2）。"""
        import socket as _socket
        s = str(e)
        low = s.lower()
        if isinstance(e, _socket.gaierror) or "getaddrinfo" in low \
                or "name or service" in low:
            return i18n.t("无法解析服务器地址（请检查网络或服务器名）")
        if isinstance(e, _socket.timeout) or "timed out" in low \
                or "timeout" in low:
            return i18n.t("连接超时（请检查网络）")
        if "refused" in low:
            return i18n.t("连接被拒绝（服务器未开放该服务）")
        if "certificate" in low or "ssl" in low:
            return i18n.t("SSL 证书校验失败")
        return f"{type(e).__name__}: {e}"

    def refresh_mails(self):
        """按账户 + 本地文件夹 + 过滤器 + 关键字组合查询（搜索下沉 SQL）。"""
        keyword = self._search_var.get().strip()
        mode = self._filter_var.get()
        self.tree.delete(*self.tree.get_children())
        rows, total = db.search_mails(
            self._filter_account, keyword,
            unread_only=(mode == i18n.t("只看未读")),
            has_attach=(mode == i18n.t("有附件")),
            local_folder=self._filter_local,
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
                                     subj, self._friendly_date(row["received_at"])),
                             tags=tuple(tags))
        filtered = len(rows)
        self.var_status.set(
            i18n.t("共 {n} 封，显示 {m} 封").format(n=total, m=filtered)
            if (keyword or mode != i18n.t("全部")) else
            i18n.t("共 {n} 封").format(n=total))

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
            self._sync_read_flags([mail])
            self.refresh_mails()
            self.refresh_accounts()
            self.root.event_generate("<<UnreadChanged>>", when="tail")
        acc = self.manager.get(mail["account_id"])
        acc_name = acc.name if acc else mail["account_id"]
        self._current_mail = mail
        self.txt_body.configure(state="normal")
        self.txt_body.delete("1.0", "end")
        self.txt_body.insert("end", mail["subject"] or i18n.t("（无主题）"), "subject")
        self.txt_body.insert("end", "\n")
        self.txt_body.insert("end",
                             i18n.t("来自 {name} <{addr}>　·　{date}　·　来源：{acc}")
                             .format(name=mail["from_name"], addr=mail["from_addr"],
                                     date=mail["received_at"], acc=acc_name)
                             + "\n", "meta")
        att_names = self._mail_attachments(mail)
        if att_names:
            self.txt_body.insert(
                "end", i18n.t("📎 附件：{names}").format(names="、".join(att_names))
                + "\n", "meta")
        self.txt_body.insert("end", "─" * 60 + "\n\n", "divider")
        body_html = mail["body_html"] if "body_html" in mail.keys() else ""
        self._photo_refs = []             # 上一封的图片引用清掉（防泄漏）
        self._img_gen = getattr(self, "_img_gen", 0) + 1
        if body_html:
            # HTML 富文本渲染（v1.10.0）：图片占位 → 异步加载回填
            self.txt_body.mark_set("renderstart", "end-1c")
            images = render_html(self.txt_body, body_html, FONT_UI, self.C)
            self.txt_body.configure(state="disabled")
            # 未闭合 <script>/<style> 会让渲染器丢弃尾部甚至全部内容：
            # 渲染结果为空且有纯文本兜底时回退（v1.10.1 审查修复）
            if not self.txt_body.get("renderstart", "end-1c").strip() \
                    and (mail["body_text"] or "").strip():
                self.txt_body.configure(state="normal")
                self.txt_body.insert("end", mail["body_text"], "body")
                self.txt_body.configure(state="disabled")
            if images:
                self._load_mail_images(mail["id"], images)
        else:
            body = mail["body_text"] or i18n.t("（无正文/解析失败）")
            self.txt_body.insert("end", body, "body")
            self.txt_body.configure(state="disabled")

    def _load_mail_images(self, mail_id: int, images):
        """后台线程加载邮件图片（v1.10.0）：CID 内嵌/远程 http/data:URI。

        限制见 imgload（每张 3MB、最多 10 张、魔数校验）；下载与 PIL 解码
        全在后台线程，PhotoImage 创建与 Text 插入回主线程。
        换邮件后到达的图片按代次丢弃（_img_gen）。
        """
        from . import imgload
        gen = self._img_gen
        acc = self.manager.get(self._current_mail["account_id"]) \
            if self._current_mail else None
        pwd = self.manager.password(acc.id) if acc else ""
        uid = self._current_mail["uid"] if self._current_mail else ""
        folder = (self._current_mail["folder"]
                  or getattr(acc, "folder", "INBOX")) if self._current_mail else "INBOX"
        need_raw = any(s.lower().startswith("cid:") for _t, s in images)
        n_loaded = 0

        def done():
            if n_loaded:
                self.var_status.set(i18n.t("已加载 {n} 张邮件图片").format(n=n_loaded))

        def work():
            nonlocal n_loaded
            cmap = {}
            if need_raw and acc is not None:
                # 会话级缓存：来回切同一封邮件不重复 IMAP 拉整封原文
                cmap = getattr(self, "_cid_cache", {}).get(mail_id)
                if cmap is None:
                    try:
                        from core.mail_client import MailClient
                        cmap = imgload.cid_map_from_raw(
                            MailClient.fetch_raw(acc, pwd, folder, uid))
                        cache = getattr(self, "_cid_cache", {})
                        # 按字节总量限界：图片字节常驻内存，防托盘长年运行膨胀
                        total = sum(len(v) for m in cache.values() for v in m.values())
                        while cache and total + sum(len(v) for v in cmap.values()) > 64 * 1024 * 1024:
                            total -= sum(len(v) for v in next(iter(cache.values())).values())
                            cache.pop(next(iter(cache)))
                        cache[mail_id] = cmap
                        self._cid_cache = cache
                    except Exception:
                        cmap = {}
            for tag, src in images:
                if self._img_gen != gen:      # 用户已切到别的邮件
                    return
                try:
                    if src.lower().startswith("cid:"):
                        data = cmap.get(imgload.cid_from_src(src), b"")
                    elif src.lower().startswith("data:"):
                        data = imgload.data_b64_from_src(src) or b""
                    else:
                        data = imgload.download(src)
                except Exception:
                    continue
                if not data:
                    continue
                im = imgload.decode(data)     # 重活全在后台线程
                if im is None:
                    continue

                def apply(tag=tag, im=im):
                    nonlocal n_loaded
                    if self._img_gen != gen:
                        return
                    try:
                        ranges = self.txt_body.tag_ranges(tag)
                        if not ranges:
                            return
                        photo = imgload.photo_from(im)   # Tk 对象须主线程建
                        if photo is None:
                            return
                        self._photo_refs.append(photo)   # 防 GC
                        self.txt_body.configure(state="normal")
                        try:
                            self.txt_body.delete(ranges[0], ranges[1])
                            self.txt_body.image_create(ranges[0], image=photo)
                        finally:
                            self.txt_body.configure(state="disabled")  # 成对回位
                        n_loaded += 1
                    except Exception:
                        pass

                self.root.after(0, apply)
            self.root.after(0, done)

        threading.Thread(target=work, name="onemail-img",
                         daemon=True).start()

    @staticmethod
    def _mail_attachments(mail) -> list[str]:
        try:
            return json.loads(mail["attachment_names"]) \
                if mail["attachment_names"] else []
        except (json.JSONDecodeError, TypeError):
            return []

    # ---------- 复制与右键菜单 ----------
    def _copy_to_clipboard(self, text: str, label: str = "内容"):
        text = (text or "").strip()
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        preview = text if len(text) <= 24 else text[:24] + "…"
        self.var_status.set(i18n.t("已复制{label}：{preview}")
                            .format(label=i18n.t(label), preview=preview))

    def _mail_list_menu(self, event):
        """邮件列表右键：复制 / 标未读 / 移动到文件夹 / 删除。"""
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
        for key, val in (
            ("复制主题", subj),
            ("复制发件人", name),
            ("复制发件人邮箱", addr),
            ("复制正文", mail["body_text"] or ""),
        ):
            menu.add_command(label=i18n.t(key),
                             state="normal" if val.strip() else "disabled",
                             command=lambda v=val, l=key[2:]: self._copy_to_clipboard(v, l))
        menu.add_separator()
        menu.add_command(label=i18n.t("标记为未读"),
                         command=self.mark_selected_unread)
        # 邮件列表右键直接新建文件夹（v1.10.0）
        menu.add_command(label=i18n.t("新建文件夹…"), command=self.create_folder)
        # 移动到本地文件夹（v1.9.0）
        folders = self._get_folders()
        if folders:
            mv = tk.Menu(menu, tearoff=0)
            for f in folders:
                mv.add_command(label=f,
                               command=lambda ff=f: self._move_selected_to(ff))
            mv.add_separator()
            mv.add_command(label=i18n.t("移回收件箱"),
                           command=lambda: self._move_selected_to(""))
            menu.add_cascade(label=i18n.t("移动到文件夹"), menu=mv)
        elif mail["local_folder"]:
            menu.add_command(label=i18n.t("移回收件箱"),
                             command=lambda: self._move_selected_to(""))
        menu.add_separator()
        menu.add_command(label=i18n.t("删除（仅本地缓存）"),
                         command=self.delete_selected_mail)
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
        self.var_status.set(i18n.t("已从本地缓存删除该邮件（服务器不受影响）"))

    def _account_menu(self, account_id: str | None, event):
        """账户面板右键：复制邮箱地址/账户名。"""
        if not account_id:
            return  # "全部邮件"卡片无地址可复制
        acc = self.manager.get(account_id)
        if acc is None:
            return
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=i18n.t("复制邮箱地址"),
                         command=lambda: self._copy_to_clipboard(acc.email, "邮箱地址"))
        menu.add_command(label=i18n.t("复制账户名"),
                         command=lambda: self._copy_to_clipboard(acc.name, "账户名"))
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()
        menu.destroy()

    def _body_menu(self, event):
        """阅读区右键：复制 / 全选 / 附件（打开/另存/全部保存）/ AI 总结。"""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=i18n.t("复制"), command=self._copy_body_selection)
        menu.add_command(label=i18n.t("全选"),
                         command=lambda: self.txt_body.tag_add("sel", "1.0", "end"))
        mail = self._current_mail
        att_names = self._mail_attachments(mail) if mail else []
        if att_names:
            att_menu = tk.Menu(menu, tearoff=0)
            for name in att_names:
                sub = tk.Menu(att_menu, tearoff=0)
                sub.add_command(label=i18n.t("打开"),
                                command=lambda n=name: self.open_attachment(n))
                sub.add_command(label=i18n.t("另存为…"),
                                command=lambda n=name: self.save_attachment_as(n))
                att_menu.add_cascade(label=name, menu=sub)
            att_menu.add_separator()
            att_menu.add_command(label=i18n.t("全部保存到…"),
                                 command=self.save_attachments)
            menu.add_cascade(label=i18n.t("附件"), menu=att_menu)
        menu.add_separator()
        menu.add_command(label=i18n.t("AI 总结"), command=self.ai_summary)
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()
        menu.destroy()

    # ---------- 附件：打开 / 另存为 / 全部保存（v1.9.0） ----------
    def _fetch_mail_attachments(self, mail, done):
        """后台取回原文并解析附件，成功后回 UI 线程调 done(atts)。"""
        from core.mail_client import MailClient
        from core.parser import extract_attachments
        acc = self.manager.get(mail["account_id"])
        if acc is None:
            self.var_status.set(i18n.t("该邮件的来源账户已被删除，无法取回附件"))
            return
        pwd = self.manager.password(acc.id)
        # 邮件行自带来源文件夹：账户后来改过收信文件夹时，
        # 用 acc.folder 会在错误的文件夹里按 UID 取到另一封邮件
        uid, folder = mail["uid"], (mail["folder"] or getattr(acc, "folder", "INBOX"))
        self.var_status.set(i18n.t("正在从服务器取回邮件原文…"))

        def work():
            try:
                raw = MailClient.fetch_raw(acc, pwd, folder, uid)
                atts = extract_attachments(raw)
                self.root.after(0, lambda: done(atts))
            except Exception as e:
                err = self._friendly_error(e)
                self.root.after(0, lambda: self.var_status.set(
                    i18n.t("附件保存失败：{err}").format(err=err)))

        threading.Thread(target=work, name="onemail-attach",
                         daemon=True).start()

    @staticmethod
    def _safe_name(name: str) -> str:
        safe = os.path.basename(name.replace("\\", "_").replace("/", "_")) or i18n.t("附件")
        reserved = {"CON", "PRN", "AUX", "NUL"} | {
            f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}
        if os.path.splitext(safe)[0].upper() in reserved:
            safe += "_"   # Windows 保留设备名（con/nul/...）不可作文件名
        return safe

    def open_attachment(self, name: str):
        """打开单个附件：取原文 → 写临时目录 → 系统默认程序打开。"""
        mail = self._current_mail
        if not mail:
            return
        tmp_dir = os.path.join(tempfile.gettempdir(), "OneMail",
                               str(mail["id"]))
        os.makedirs(tmp_dir, exist_ok=True)
        path = os.path.join(tmp_dir, self._safe_name(name))
        if os.path.exists(path):
            # 之前取过：直接复用，不再连服务器
            os.startfile(path)
            return

        def done(atts):
            data = next((d for n, d in atts if n == name
                         or self._safe_name(n) == self._safe_name(name)), None)
            if data is None:
                self.var_status.set(i18n.t("未在服务器原文中解析出附件"))
                return
            with open(path, "wb") as f:
                f.write(data)
            os.startfile(path)
            self.var_status.set(i18n.t("已打开：{name}").format(name=name))

        self._fetch_mail_attachments(mail, done)

    def save_attachment_as(self, name: str):
        """单个附件另存为（如 PDF 自选路径）。"""
        mail = self._current_mail
        if not mail:
            return
        dest = filedialog.asksaveasfilename(
            parent=self.root, initialfile=self._safe_name(name),
            title=i18n.t("另存为…"))
        if not dest:
            return

        def done(atts):
            data = next((d for n, d in atts if n == name
                         or self._safe_name(n) == self._safe_name(name)), None)
            if data is None:
                self.var_status.set(i18n.t("未在服务器原文中解析出附件"))
                return
            with open(dest, "wb") as f:
                f.write(data)
            self.var_status.set(i18n.t("已保存：{path}").format(path=dest))

        self._fetch_mail_attachments(mail, done)

    def save_attachments(self):
        """把当前邮件的附件保存到所选目录（按 UID 从服务器重新取原文）。"""
        mail = self._current_mail
        if not mail or not mail["has_attachment"]:
            return
        dest = filedialog.askdirectory(parent=self.root,
                                       title=i18n.t("选择附件保存位置"))
        if not dest:
            return

        def done(atts):
            if not atts:
                self.var_status.set(i18n.t("未在服务器原文中解析出附件"))
                return
            saved = 0
            for name, data in atts:
                path = os.path.join(dest, self._safe_name(name))
                stem, ext = os.path.splitext(path)
                n = 1
                while os.path.exists(path):
                    path = f"{stem}({n}){ext}"
                    n += 1
                with open(path, "wb") as f:
                    f.write(data)
                saved += 1
            self.var_status.set(i18n.t("已保存 {n} 个附件到 {dest}")
                                .format(n=saved, dest=dest))

        self._fetch_mail_attachments(mail, done)

    def _copy_body_selection(self):
        try:
            text = self.txt_body.get("sel.first", "sel.last")
        except tk.TclError:
            text = ""
        self._copy_to_clipboard(text, "选中内容")

    # ---------- AI 总结（v1.9.0） ----------
    def ai_summary(self):
        """AI 总结当前阅读的邮件（OpenAI 兼容接口，后台线程请求）。"""
        from core import ai_client
        mail = self._current_mail
        if mail is None:
            return
        base_url, model, key = self._ai_conf()
        if not base_url or not key:
            messagebox.showinfo(i18n.t("一邮通"),
                                i18n.t("请先配置 AI（设置 → AI 功能）"),
                                parent=self.root)
            return
        acc = self.manager.get(mail["account_id"])
        acc_name = acc.name if acc else ""
        subject = mail["subject"] or ""
        sender = mail["from_name"] or mail["from_addr"] or ""
        sender = f"{sender} ({acc_name})" if acc_name else sender
        body = mail["body_text"] or ""
        self.var_status.set(i18n.t("正在请求 AI…"))

        def work():
            try:
                result = ai_client.summarize(base_url, key, model,
                                             subject, sender, body)
            except Exception as e:
                result = ""
                err = f"{type(e).__name__}: {e}"
                self.root.after(0, lambda: self.var_status.set(
                    i18n.t("AI 总结失败：{err}").format(err=err)))
            else:
                self.root.after(0, lambda: self._show_ai_result(subject, result))

        threading.Thread(target=work, name="onemail-ai", daemon=True).start()

    def _show_ai_result(self, subject: str, text: str):
        self.var_status.set(i18n.t("就绪"))
        if not text:
            text = i18n.t("AI 未返回内容")
        win = tk.Toplevel(self.root)
        win.title(f"{i18n.t('AI 总结')} · {subject[:40]}")
        win.geometry("560x440")
        win.transient(self.root)
        txt = tk.Text(win, wrap="word", font=FONT_UI, bd=0, padx=14, pady=12,
                      bg=self.C["CARD"], fg=self.C["TEXT"])
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", text)
        txt.configure(state="disabled")
        bar = tk.Frame(win, bg=self.C["CARD"])
        bar.pack(fill="x")
        ttk.Button(bar, text=i18n.t("复制结果"),
                   command=lambda: self._copy_ai_text(win, txt)).pack(
            side="right", padx=8, pady=8)
        ttk.Button(bar, text=i18n.t("关闭"),
                   command=win.destroy).pack(side="right", pady=8)

    def _copy_ai_text(self, win, txt):
        self.root.clipboard_clear()
        self.root.clipboard_append(txt.get("1.0", "end").strip())
        self.var_status.set(i18n.t("已复制{label}：{preview}")
                            .format(label=i18n.t("内容"), preview="AI …"))

    def fetch_now(self):
        n = 0
        for acc in self.manager.enabled():
            client = self.scheduler.client(acc.id)
            if client is not None and not client.stopped:
                client.wake()   # 真正打断 IDLE 等待/轮询睡眠，立即抓一次
                n += 1
        self.var_status.set(i18n.t("已请求 {n} 个账户立即收信").format(n=n))

    def _sync_read_flags(self, rows, seen: bool = True):
        """把已读/未读变化投递给后台线程写回服务器（v1.7.0）。

        只投递、不等待：网络在 flag_sync 后台线程进行，失败只记日志。
        folder 用邮件行内记录的来源文件夹（教训同保存附件：acc.folder 可能已改）。
        """
        if self.flag_sync is None:
            return
        jobs = []
        for r in rows:
            try:
                folder = r["folder"] or "INBOX"
            except (IndexError, KeyError):
                folder = "INBOX"
            jobs.append((r["account_id"], folder, r["uid"], seen))
        self.flag_sync.submit_many(jobs)

    def mark_all_read(self, account_id: str | None | object = "__filter__"):
        """全部标为已读。

        account_id 默认 "__filter__" = 尊重当前账户筛选（工具栏按钮）；
        传 None = 全部账户（托盘路径），传账户 id = 指定账户。
        """
        if account_id == "__filter__":
            account_id = self._filter_account
        # 同事务内取未读行 + 置已读（v1.8.1）：间隙入库的新邮件不会被
        # "已读但漏投递"，造成本地/服务器永久不一致
        rows = db.mark_all_read_synced(account_id)
        self._sync_read_flags(rows, seen=True)
        self.full_refresh()
        self.root.event_generate("<<UnreadChanged>>", when="tail")

    def mark_selected_read(self):
        sel = self.tree.selection()
        if not sel:
            return
        mail = db.get_mail(int(sel[0]))
        if mail is None:
            return
        db.mark_read(mail["id"])
        self._sync_read_flags([mail], seen=True)
        self.refresh_mails()
        self.refresh_accounts()
        self.root.event_generate("<<UnreadChanged>>", when="tail")

    def mark_selected_unread(self):
        """标记为未读：本地置回未读，并经 flag_sync 向服务器 -FLAGS \\Seen（v1.8.0）。"""
        sel = self.tree.selection()
        if not sel:
            return
        mail = db.get_mail(int(sel[0]))
        if mail is None or not mail["is_read"]:
            return  # 已是未读：短路，免一次无谓的服务器短连接
        db.mark_read(mail["id"], read=False)
        self._sync_read_flags([mail], seen=False)
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
            messagebox.showinfo(i18n.t("一邮通"), i18n.t("请先选中要回复的邮件"))
            return
        mail = db.get_mail(int(sel[0]))
        if mail is None:
            return
        acc = self.manager.get(mail["account_id"])
        reply_to = mail["from_addr"] or ""
        subj = mail["subject"] or ""
        if subj and not subj.startswith(("回复：", "回复:", "Re:", "Re:")):
            subj = i18n.t("回复：{subj}").format(subj=subj)
        quote = (f"\n\n-------- {i18n.t('原始邮件')} --------\n"
                 f"{i18n.t('发件人')}：{mail['from_name'] or reply_to} <{reply_to}>\n"
                 f"{i18n.t('时间')}：{mail['received_at']}\n"
                 f"{i18n.t('主题')}：{mail['subject'] or ''}\n\n"
                 f"{mail['body_text'] or ''}\n")
        ComposeWindow(self.root, self.manager, account=acc, to=reply_to,
                      subject=subj, body=quote)

    def edit_account(self):
        acc = self._selected_account()
        if acc is None:
            messagebox.showinfo(i18n.t("一邮通"),
                                i18n.t("请先在左侧列表选中要编辑的账户"))
            return
        AccountDialog(self.root, self.manager, account=acc,
                      on_saved=lambda a, p: self._on_account_saved(a, p))

    def prompt_missing_password(self):
        """启动时若有账户缺密码，自动弹出编辑框录入授权码（保存后继续下一个）。"""
        for acc in self.manager.all():
            if acc.enabled and not self.manager.password(acc.id) \
                    and getattr(acc, "auth_type", "password") != "oauth2":
                self.var_status.set(
                    i18n.t("账户 {name} 缺少授权码，请输入").format(name=acc.name))

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
        self.var_status.set(
            i18n.t("账户 {name} 已保存，开始连接 {host} …")
            .format(name=acc.name, host=acc.imap_host))

    def remove_account(self):
        acc = self._selected_account()
        if acc is None:
            messagebox.showinfo(i18n.t("一邮通"),
                                i18n.t("请先在左侧列表选中要删除的账户"))
            return
        if not messagebox.askyesno(
                i18n.t("一邮通"),
                i18n.t("删除账户 {name}？\n该账户的本地邮件缓存将一并删除。")
                .format(name=acc.name)):
            return
        self.scheduler.stop_account(acc.id)
        self.manager.remove(acc.id)
        db.delete_account_mails(acc.id)
        self._account_status.pop(acc.id, None)
        self._filter_account = None
        self.full_refresh()
        self.root.event_generate("<<UnreadChanged>>", when="tail")

    def set_status(self, text: str):
        self.var_status.set(_tr_status(text))
