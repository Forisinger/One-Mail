# -*- coding: utf-8 -*-
"""添加/编辑邮箱账户对话框。

v1.10.0：支持 OAuth2（Gmail/Outlook）——认证方式下拉、client_id/secret 录入、
「浏览器登录」按钮（授权码 + PKCE + loopback 回调，后台线程跑，不阻塞 UI）。
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox

from core.account import Account, AccountManager, OAUTH_DOMAINS, oauth_provider_for
from . import i18n

_AUTH_LABELS = (i18n.t("授权码 / 密码"), i18n.t("OAuth2（Gmail / Outlook）"))
_AUTH_BY_LABEL = {_AUTH_LABELS[0]: "password", _AUTH_LABELS[1]: "oauth2"}


class AccountDialog(tk.Toplevel):
    """录入：显示名 / 邮箱 / 密码 / IMAP 服务器 / 端口 / SSL / 认证方式。

    保存后回调 on_saved(account, password)。
    """

    def __init__(self, master, manager: AccountManager,
                 account: Account | None = None, on_saved=None):
        super().__init__(master)
        self.manager = manager
        self.account = account
        self.on_saved = on_saved
        self.title(i18n.t("编辑账户") if account else i18n.t("添加账户"))
        self.resizable(False, False)
        self.grab_set()  # 模态

        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=12, pady=10)

        row_counter = [0]

        def row(label, widget_factory):
            r = row_counter[0]
            row_counter[0] += 1
            lbl = ttk.Label(frm, text=label)
            lbl.grid(row=r, column=0, sticky="e", **pad)
            w = widget_factory()
            w.grid(row=r, column=1, sticky="we", **pad)
            w._row_label = lbl    # 认证方式切换时整行联动隐藏
            return w

        self.var_name = tk.StringVar()
        self.var_email = tk.StringVar(value=account.email if account else "")
        self.var_pass = tk.StringVar()
        self.var_host = tk.StringVar(value=account.imap_host if account else "")
        self.var_port = tk.StringVar(value=str(account.imap_port if account else 993))
        self.var_ssl = tk.BooleanVar(value=account.ssl if account else True)
        folder = account.folder if account else "INBOX"
        self.var_folder = tk.StringVar(value=folder or "INBOX")
        init_auth = getattr(account, "auth_type", "password") or "password"
        self.var_auth = tk.StringVar(
            value=_AUTH_LABELS[1] if init_auth == "oauth2" else _AUTH_LABELS[0])
        self.var_client_id = tk.StringVar(value=getattr(account, "client_id", "") or "")
        self.var_client_secret = tk.StringVar(
            value=getattr(account, "client_secret", "") or "")

        w0 = row(i18n.t("显示名："), lambda: ttk.Entry(frm, textvariable=self.var_name, width=30))
        w1 = row(i18n.t("邮箱地址："), lambda: ttk.Entry(frm, textvariable=self.var_email, width=30))
        wA = row(i18n.t("认证方式："), lambda: ttk.Combobox(
            frm, textvariable=self.var_auth, state="readonly", width=28,
            values=list(_AUTH_LABELS)))
        self.var_auth.trace_add("write", lambda *_: self._auth_touched())
        self._w_pass = row(i18n.t("密码/授权码："), lambda: ttk.Entry(
            frm, textvariable=self.var_pass, width=30, show="*"))
        w3 = row(i18n.t("IMAP 服务器："), lambda: ttk.Entry(frm, textvariable=self.var_host, width=30))
        w4 = row(i18n.t("端口："), lambda: ttk.Entry(frm, textvariable=self.var_port, width=10))
        w5 = row(i18n.t("SSL："), lambda: ttk.Checkbutton(frm, variable=self.var_ssl))

        # OAuth2 凭据（密码账户忽略这两行）
        oauth_cell = ttk.Frame(frm)
        self.ent_client_id = ttk.Entry(oauth_cell, textvariable=self.var_client_id, width=24)
        self.ent_client_id.pack(side="left", fill="x", expand=True)
        self.btn_oauth_login = ttk.Button(
            oauth_cell, text=i18n.t("浏览器登录"), command=self._oauth_login)
        self.btn_oauth_login.pack(side="left", padx=(6, 0))
        self.lbl_oauth_tip = ttk.Label(oauth_cell, foreground="#888", text="")
        self.lbl_oauth_tip.pack(side="left", padx=(6, 0))
        wCID = row(i18n.t("OAuth2 Client ID："), lambda: oauth_cell)
        wSEC = row(i18n.t("Client Secret（可选）："), lambda: ttk.Entry(
            frm, textvariable=self.var_client_secret, width=30, show="*"))
        self._w_cid, self._w_sec = wCID, wSEC

        # 收信文件夹：可手填，也可点「获取」从服务器拉取列表
        folder_cell = ttk.Frame(frm)
        self.cmb_folder = ttk.Combobox(folder_cell, textvariable=self.var_folder, width=22)
        self.cmb_folder.pack(side="left", fill="x", expand=True)
        self.btn_fetch_folders = ttk.Button(folder_cell, text=i18n.t("获取"),
                                            command=self._fetch_folders)
        self.btn_fetch_folders.pack(side="left", padx=(6, 0))
        self.lbl_folder_tip = ttk.Label(folder_cell, foreground="#888", text="")
        self.lbl_folder_tip.pack(side="left", padx=(6, 0))
        w6 = row(i18n.t("收信文件夹："), lambda: folder_cell)

        w1.bind("<FocusOut>", self._autofill_host)
        for w in (w0, w1, wA, self._w_pass, w3, w4, w5, wCID, wSEC, w6):
            frm.columnconfigure(1, weight=1)

        hint = ttk.Label(self, foreground="#888", justify="left",
                         text=i18n.t("提示：QQ/163 等国内邮箱用「授权码」；Gmail/Outlook 选 OAuth2，"
                                     "需先在 Google Cloud / Azure 注册应用拿到 Client ID。"))
        hint.pack(anchor="w", padx=12)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=8)
        ttk.Button(btns, text=i18n.t("取消"), command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text=i18n.t("保存"), command=self._save).pack(side="right")

        self._auth_touched()

    # ---------- 认证方式联动 ----------

    def _is_oauth(self) -> bool:
        return _AUTH_BY_LABEL.get(self.var_auth.get()) == "oauth2"

    def _auth_touched(self):
        """OAuth2 时隐藏密码行（凭据走令牌），密码账户隐藏 OAuth2 行。"""
        oauth = self._is_oauth()
        self._set_row_visible(self._w_pass, not oauth)
        self._set_oauth_rows_visible(oauth)

    def _set_row_visible(self, w, visible: bool):
        """整行显示/隐藏（控件 + 左侧标签）。"""
        (w.grid if visible else w.grid_remove)()
        lbl = getattr(w, "_row_label", None)
        if lbl is not None:
            (lbl.grid if visible else lbl.grid_remove)()

    def _set_oauth_rows_visible(self, visible: bool):
        self._set_row_visible(self._w_cid, visible)
        self._set_row_visible(self._w_sec, visible)

    def _oauth_login(self):
        """后台线程跑授权码+PKCE 流程，浏览器弹出，状态回显到标签。"""
        email_addr = self.var_email.get().strip()
        client_id = self.var_client_id.get().strip()
        if "@" not in email_addr or not client_id:
            self.lbl_oauth_tip.configure(text=i18n.t("请先填写邮箱与 Client ID"))
            return
        provider = oauth_provider_for(email_addr)
        if provider is None:
            self.lbl_oauth_tip.configure(text=i18n.t("未识别的 OAuth2 域名（仅支持 Gmail/Outlook）"))
            return
        self.btn_oauth_login.configure(state="disabled")
        self.lbl_oauth_tip.configure(text=i18n.t("已打开浏览器，请完成登录…"))

        def worker():
            from core import oauth2
            try:
                oauth2.authorize(provider, email_addr, client_id,
                                 self.var_client_secret.get().strip())
                self._dialog_after(lambda: self.lbl_oauth_tip.configure(
                    text=i18n.t("登录成功，令牌已保存")))
            except Exception as e:
                self._dialog_after(lambda: self.lbl_oauth_tip.configure(
                    text=i18n.t("登录失败：{err}").format(err=e)))
            finally:
                self._dialog_after(lambda: self.btn_oauth_login.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _autofill_host(self, _evt=None):
        if self._is_oauth():
            # OAuth2 域名直接用官方服务器预置（guess_host 对 outlook 系会猜错）
            email_addr = self.var_email.get().strip()
            domain = email_addr.rsplit("@", 1)[-1].lower()
            for d, (_provider, smtp_host, smtp_port) in OAUTH_DOMAINS.items():
                if domain == d or domain.endswith("." + d):
                    self.var_host.set("imap.gmail.com" if _provider == "google"
                                      else "outlook.office365.com")
                    if not self.var_port.get().strip() or self.var_port.get() == "993":
                        self.var_port.set("993")
                    return
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
        """子线程连接服务器 LIST 文件夹，成功后回填下拉列表。

        线程安全：所有 tk 变量在启动线程**之前**取值；回填统一经
        after 投递回主线程并判断窗口存活（用户可能中途关闭对话框）。
        """
        host = self.var_host.get().strip()
        email_addr = self.var_email.get().strip()
        use_ssl = self.var_ssl.get()
        password = self.var_pass.get()
        if not password and self.account:
            password = self.manager.password(self.account.id)
        if not host or "@" not in email_addr:
            self.lbl_folder_tip.configure(text=i18n.t("请先填写邮箱与服务器"))
            return
        try:
            port = int(self.var_port.get().strip() or 993)
        except ValueError:
            self.lbl_folder_tip.configure(text=i18n.t("端口必须是数字"))
            return
        is_oauth = self._is_oauth()

        def worker():
            from core.mail_client import MailClient
            acc_probe = Account(
                id="probe", name="", email=email_addr,
                imap_host=host, imap_port=port, ssl=use_ssl,
                auth_type="oauth2" if is_oauth else "password",
                client_id=self.var_client_id.get().strip(),
                client_secret=self.var_client_secret.get().strip())
            try:
                folders = MailClient.list_folders(acc_probe, password)
            except Exception as e:
                self._dialog_after(lambda: self.lbl_folder_tip.configure(
                    text=i18n.t("获取失败：{err}").format(err=type(e).__name__)))
                return
            self._dialog_after(lambda: (
                self.cmb_folder.configure(values=folders),
                self.lbl_folder_tip.configure(text=f"共 {len(folders)} 个文件夹"),
            ))

        self.lbl_folder_tip.configure(text=i18n.t("正在连接…"))
        threading.Thread(target=worker, daemon=True).start()

    def _dialog_after(self, fn):
        """窗口可能已被用户关闭：投递回主线程，静默忽略已销毁的情况。"""
        try:
            self.after(0, self._safe_apply, fn)
        except Exception:
            pass

    @staticmethod
    def _safe_apply(fn):
        try:
            fn()
        except Exception:
            pass  # 控件已销毁（对话框已关闭），忽略

    def _save(self):
        email_addr = self.var_email.get().strip()
        password = self.var_pass.get()
        host = self.var_host.get().strip()
        is_oauth = self._is_oauth()
        if "@" not in email_addr:
            messagebox.showwarning(i18n.t("一邮通"), i18n.t("请填写正确的邮箱地址"), parent=self)
            return
        if not host:
            host, port = Account.guess_host(email_addr)
        try:
            port = int(self.var_port.get().strip() or 993)
        except ValueError:
            messagebox.showwarning(i18n.t("一邮通"), i18n.t("端口必须是数字"), parent=self)
            return

        if is_oauth:
            client_id = self.var_client_id.get().strip()
            if not client_id:
                messagebox.showwarning(i18n.t("一邮通"),
                                       i18n.t("OAuth2 需要填写 Client ID"), parent=self)
                return
            from core.oauth2 import load_token
            if load_token(email_addr) is None:
                messagebox.showwarning(i18n.t("一邮通"),
                                       i18n.t("请先点「浏览器登录」完成 OAuth2 授权"), parent=self)
                return
            password = ""          # OAuth2 账户无密码，凭据在令牌里
        else:
            if not password and self.account is None:
                messagebox.showwarning(i18n.t("一邮通"), i18n.t("请填写密码或授权码"), parent=self)
                return
            if not password:
                # 编辑已有账户：留空表示沿用已存的授权码，不必每次重输
                password = self.manager.password(self.account.id)
                if not password:
                    messagebox.showwarning(i18n.t("一邮通"), i18n.t("该账户尚无已存授权码，请填写"), parent=self)
                    return

        name = self.var_name.get().strip() or email_addr
        folder = self.var_folder.get().strip() or "INBOX"
        # OAuth2 域名显式设置 SMTP 预置（smtp_endpoint 推导对 outlook 系不成立）
        smtp_host, smtp_port = "", 465
        if is_oauth:
            domain = email_addr.rsplit("@", 1)[-1].lower()
            for d, (_p, sh, sp) in OAUTH_DOMAINS.items():
                if domain == d or domain.endswith("." + d):
                    smtp_host, smtp_port = sh, sp
                    break

        if self.account:
            # v1.8.1：构造全新 Account 原子替换（update 内整体覆盖 dict 条目），
            # 避免逐字段原地赋值被收信/flag_sync 线程读到"新 host + 旧 port"撕裂组合
            old = self.account
            conn_changed = (old.imap_host, old.imap_port, old.ssl) != \
                (host, port, self.var_ssl.get())
            new_acc = Account(
                id=old.id, name=name, email=email_addr,
                imap_host=host, imap_port=port, ssl=self.var_ssl.get(),
                enabled=old.enabled, folder=folder,
                idle_supported=None if conn_changed else old.idle_supported,
                poll_interval=old.poll_interval,
                smtp_host=smtp_host or old.smtp_host,
                smtp_port=smtp_port if smtp_host else old.smtp_port,
                auth_type="oauth2" if is_oauth else "password",
                client_id=self.var_client_id.get().strip(),
                client_secret=self.var_client_secret.get().strip(),
                extra=old.extra,
            )
            self.manager.update(new_acc, password=password or None)
            acc, pwd = new_acc, password
        else:
            acc = self.manager.add(name, email_addr, password,
                                   imap_host=host, imap_port=port,
                                   ssl=self.var_ssl.get())
            acc.folder = folder
            acc.auth_type = "oauth2" if is_oauth else "password"
            acc.client_id = self.var_client_id.get().strip()
            acc.client_secret = self.var_client_secret.get().strip()
            if smtp_host:
                acc.smtp_host, acc.smtp_port = smtp_host, smtp_port
            self.manager.update(acc, password=password or None)
            pwd = password
        if self.on_saved:
            self.on_saved(acc, pwd)
        self.destroy()
