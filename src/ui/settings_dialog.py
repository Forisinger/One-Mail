# -*- coding: utf-8 -*-
"""设置对话框（v1.9.0 建立，v1.11.0 扩展为多页签）。

页签划分（把原先散落各处的应用级开关集中到一处）：
- 外观：语言 / 主题 / 强调色（可自定义并恢复默认）
- AI 功能：OpenAI 兼容接口的 base_url / model / API Key
- 其他：开机自启（原先只能改注册表）、同步已读到服务器（原先只在托盘）、打开日志文件夹

语言与主题/强调色写入 config 后提示**重启生效**（tkinter 控件颜色与文案在
构造时固化，运行时全量重绘的复杂度远超收益）。
AI Key 经 core.security（DPAPI）加密存储，绝不明文落盘；留空 = 沿用已存 key。
"""
from __future__ import annotations

import os

import tkinter as tk
from tkinter import ttk, messagebox, colorchooser

from storage import config as config_store
from core import security
import autostart          # src 顶层模块（注册表自启开关），非 core 包内
from . import i18n
from . import theme as theme_mod

_THEME_LABELS = {"light": "浅色", "dark": "深色"}
_LANG_LABELS = {"zh": "中文", "en": "English"}


class SettingsDialog(tk.Toplevel):
    def __init__(self, master, on_saved=None):
        super().__init__(master)
        self.on_saved = on_saved
        self.C = theme_mod.window_colors(self)   # 窗口底跟随主题（v1.11.2）
        self.title(i18n.t("设置"))
        self.resizable(False, False)
        self.grab_set()
        self.transient(master)

        cfg = config_store.load().get("settings", {})
        cur_theme = cfg.get("theme", theme_mod.DEFAULT_THEME)
        self._theme_key = cur_theme if cur_theme in theme_mod.THEMES \
            else theme_mod.DEFAULT_THEME
        # 待写入的强调色覆盖（'' = 用主题默认）
        self._accent = theme_mod.accent_override(self._theme_key)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=(10, 4))
        self._tab_appearance(nb, cfg)
        self._tab_ai(nb, cfg)
        self._tab_misc(nb, cfg)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=(0, 10))
        ttk.Button(btns, text=i18n.t("取消"),
                   command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text=i18n.t("保存"),
                   command=self._save).pack(side="right")

    # ---------- 外观 ----------
    def _tab_appearance(self, nb: ttk.Notebook, cfg: dict):
        c = self.C
        frm = ttk.Frame(nb, padding=14)
        nb.add(frm, text=i18n.t("外观"))
        r = 0

        ttk.Label(frm, text=i18n.t("语言（重启生效）")).grid(
            row=r, column=0, sticky="e", padx=(0, 10), pady=6)
        self.cmb_lang = ttk.Combobox(
            frm, state="readonly", width=26, values=list(_LANG_LABELS.values()))
        lang = cfg.get("language", i18n.DEFAULT_LANG)
        self.cmb_lang.current(list(_LANG_LABELS).index(
            lang if lang in i18n.LANGS else i18n.DEFAULT_LANG))
        self.cmb_lang.grid(row=r, column=1, sticky="w", pady=6)

        r += 1
        ttk.Label(frm, text=i18n.t("主题（重启生效）")).grid(
            row=r, column=0, sticky="e", padx=(0, 10), pady=6)
        self.cmb_theme = ttk.Combobox(
            frm, state="readonly", width=26,
            values=[i18n.t(v) for v in _THEME_LABELS.values()])
        self.cmb_theme.current(list(_THEME_LABELS).index(self._theme_key))
        self.cmb_theme.grid(row=r, column=1, sticky="w", pady=6)
        self.cmb_theme.bind("<<ComboboxSelected>>", self._on_theme_changed)

        r += 1
        ttk.Label(frm, text=i18n.t("强调色（重启生效）")).grid(
            row=r, column=0, sticky="e", padx=(0, 10), pady=6)
        acc_row = ttk.Frame(frm)
        acc_row.grid(row=r, column=1, sticky="w", pady=6)
        self._swatch = tk.Label(acc_row, width=4, height=1, relief="solid",
                                bd=1, bg=c["CARD"])   # 稍后由 _refresh_accent_ui 填色
        self._swatch.pack(side="left", padx=(0, 8))
        ttk.Button(acc_row, text=i18n.t("选择颜色…"),
                   command=self._pick_accent).pack(side="left")
        ttk.Button(acc_row, text=i18n.t("恢复默认"),
                   command=self._reset_accent).pack(side="left", padx=6)

        r += 1
        self._accent_tip = ttk.Label(frm, foreground=c["GRAY"], text="")
        self._accent_tip.grid(row=r, column=1, sticky="w")

        r += 1
        ttk.Label(frm, foreground=c["GRAY"],
                  text=i18n.t("主题与强调色在下次启动后生效。")).grid(
            row=r, column=1, sticky="w", pady=(6, 0))
        self._refresh_accent_ui()
        frm.columnconfigure(1, weight=1)

    def _on_theme_changed(self, _evt=None):
        """切换主题下拉：载入该主题已保存的强调色覆盖并刷新预览。"""
        self._theme_key = list(_THEME_LABELS)[self.cmb_theme.current()]
        self._accent = theme_mod.accent_override(self._theme_key)
        self._refresh_accent_ui()

    def _effective_preview(self) -> str:
        return self._accent or theme_mod.default_accent(self._theme_key)

    def _refresh_accent_ui(self):
        preview = self._effective_preview()
        try:
            self._swatch.configure(bg=preview)
        except tk.TclError:
            pass
        self._accent_tip.configure(
            text=(preview if self._accent
                  else i18n.t("默认：{color}").format(color=preview)))

    def _pick_accent(self):
        color = colorchooser.askcolor(parent=self,
                                      initialcolor=self._effective_preview())
        if not color or not color[1]:
            return
        acc = theme_mod.normalize_hex(color[1])
        if not acc:
            return
        self._accent = acc
        self._refresh_accent_ui()

    def _reset_accent(self):
        self._accent = ""
        self._refresh_accent_ui()

    # ---------- AI ----------
    def _tab_ai(self, nb: ttk.Notebook, cfg: dict):
        c = self.C
        frm = ttk.Frame(nb, padding=14)
        nb.add(frm, text=i18n.t("AI 功能"))
        ai = cfg.get("ai", {}) or {}
        r = 0

        ttk.Label(frm, text=i18n.t("API 地址：")).grid(
            row=r, column=0, sticky="e", padx=(0, 10), pady=6)
        self.var_base = tk.StringVar(
            value=ai.get("base_url", "https://api.deepseek.com/v1"))
        ttk.Entry(frm, textvariable=self.var_base, width=42).grid(
            row=r, column=1, sticky="we", pady=6)

        r += 1
        ttk.Label(frm, text=i18n.t("模型：")).grid(
            row=r, column=0, sticky="e", padx=(0, 10), pady=6)
        self.var_model = tk.StringVar(value=ai.get("model", "deepseek-chat"))
        ttk.Entry(frm, textvariable=self.var_model, width=42).grid(
            row=r, column=1, sticky="we", pady=6)

        r += 1
        ttk.Label(frm, text=i18n.t("API Key：")).grid(
            row=r, column=0, sticky="e", padx=(0, 10), pady=6)
        self.var_key = tk.StringVar()
        ttk.Entry(frm, textvariable=self.var_key, width=42, show="*").grid(
            row=r, column=1, sticky="we", pady=6)
        if security.load_password("__ai__"):
            ttk.Label(frm, foreground=c["GRAY"],
                      text=i18n.t("（已保存，留空沿用）")).grid(
                row=r, column=2, padx=(6, 0))

        r += 1
        ttk.Label(frm, foreground=c["GRAY"],
                  text=i18n.t("Key 经 Windows DPAPI 加密存储")).grid(
            row=r, column=1, sticky="w")
        r += 1
        ttk.Label(frm, foreground=c["GRAY"],
                  text=i18n.t("示例：https://api.deepseek.com/v1")).grid(
            row=r, column=1, sticky="w")
        frm.columnconfigure(1, weight=1)

    # ---------- 其他 ----------
    def _tab_misc(self, nb: ttk.Notebook, cfg: dict):
        frm = ttk.Frame(nb, padding=14)
        nb.add(frm, text=i18n.t("其他"))
        r = 0

        self.var_autostart = tk.BooleanVar(value=autostart.enabled())
        ttk.Checkbutton(frm, text=i18n.t("开机自启（用户级，无需管理员）"),
                        variable=self.var_autostart).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=4)

        r += 1
        self.var_sync = tk.BooleanVar(
            value=bool(cfg.get("sync_read_flags", True)))
        ttk.Checkbutton(
            frm, text=i18n.t("同步已读到服务器（关闭后只改本地）"),
            variable=self.var_sync).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=4)

        r += 1
        ttk.Separator(frm).grid(row=r, column=0, columnspan=2,
                                sticky="we", pady=(10, 8))
        r += 1
        # onemail.log 是排障唯一入口，给用户自助路径
        ttk.Button(frm, text=i18n.t("打开日志文件夹"),
                   command=self._open_data_dir).grid(
            row=r, column=0, sticky="w")

    def _open_data_dir(self):
        from storage.config import data_dir
        try:
            os.startfile(data_dir())   # noqa: S606 Windows 专属项目
        except Exception:
            pass

    # ---------- 保存 ----------
    def _save(self):
        theme_key = list(_THEME_LABELS)[self.cmb_theme.current()]
        try:
            cfg = config_store.load()
            st = cfg.setdefault("settings", {})
            st["language"] = list(_LANG_LABELS)[self.cmb_lang.current()]
            st["theme"] = theme_key
            st["sync_read_flags"] = bool(self.var_sync.get())
            st["autostart"] = bool(self.var_autostart.get())
            ai = st.setdefault("ai", {})
            ai["base_url"] = self.var_base.get().strip()
            ai["model"] = self.var_model.get().strip()
            key = self.var_key.get().strip()
            if key:
                security.save_password("__ai__", key)
            config_store.save(cfg)
        except Exception as e:
            messagebox.showerror(i18n.t("一邮通"),
                                 i18n.t("保存失败：{err}").format(err=e),
                                 parent=self)
            return

        # 强调色覆盖单独写（内部 load→save，读到的是上面刚保存的内容）
        theme_mod.set_accent(theme_key, self._accent)

        # 注册表自启：与当前实际状态不一致才动，失败明确提示（不改回勾选状态，
        # 以注册表实际结果为准，避免用户以为设置成功）
        want = bool(self.var_autostart.get())
        if want != autostart.enabled():
            if not autostart.set_enabled(want):
                messagebox.showwarning(
                    i18n.t("一邮通"), i18n.t("开机自启设置失败（可能被安全软件拦截）"),
                    parent=self)
        if self.on_saved:
            try:
                self.on_saved()
            except Exception:
                pass
        messagebox.showinfo(i18n.t("一邮通"),
                            i18n.t("设置已保存，语言/主题重启后生效。"),
                            parent=self)
        self.destroy()
