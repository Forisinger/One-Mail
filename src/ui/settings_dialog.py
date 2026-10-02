# -*- coding: utf-8 -*-
"""设置对话框（v1.9.0）：语言 / 主题 / AI 配置。

- 语言与主题：写入 config 后提示重启生效（tkinter 控件颜色与文案在
  构造时固化，运行时全量重绘的复杂度远超收益）。
- AI：base_url / model 存 config；API Key 经 core.security（DPAPI）加密
  存储，绝不明文落盘。key 输入框留空 = 沿用已存 key。
"""
from __future__ import annotations

import os

import tkinter as tk
from tkinter import ttk, messagebox

from storage import config as config_store
from core import security
from . import i18n
from .theme import THEMES

_THEME_LABELS = {"light": "浅色", "dark": "深色"}
_THEME_BY_LABEL = {v: k for k, v in _THEME_LABELS.items()}
_LANG_LABELS = {"zh": "中文", "en": "English"}
_LANG_BY_LABEL = {v: k for k, v in _LANG_LABELS.items()}

class SettingsDialog(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title(i18n.t("设置"))
        self.resizable(False, False)
        self.grab_set()
        self.transient(master)

        cfg = config_store.load().get("settings", {})
        ai = cfg.get("ai", {})

        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=14, pady=10)

        r = 0
        ttk.Label(frm, text=i18n.t("语言（重启生效）")).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=6)
        self.cmb_lang = ttk.Combobox(
            frm, state="readonly", width=24,
            values=list(_LANG_LABELS.values()))
        self.cmb_lang.current(list(_LANG_LABELS).index(
            cfg.get("language", i18n.DEFAULT_LANG) if cfg.get("language") in i18n.LANGS
            else i18n.DEFAULT_LANG))
        self.cmb_lang.grid(row=r, column=1, sticky="w", pady=6)

        r += 1
        ttk.Label(frm, text=i18n.t("主题（重启生效）")).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=6)
        theme_values = [i18n.t(v) for v in _THEME_LABELS.values()]
        self.cmb_theme = ttk.Combobox(
            frm, state="readonly", width=24, values=theme_values)
        theme = cfg.get("theme", "light")
        self.cmb_theme.current(theme_values.index(
            i18n.t(_THEME_LABELS.get(theme if theme in THEMES else "light",
                               "浅色"))))
        self.cmb_theme.grid(row=r, column=1, sticky="w", pady=6)

        r += 1
        ttk.Separator(frm).grid(row=r, column=0, columnspan=2,
                                sticky="we", pady=(10, 6))

        r += 1
        ttk.Label(frm, text=i18n.t("AI 功能（OpenAI 兼容接口）"),
                  font=("Microsoft YaHei UI", 10, "bold")).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(0, 6))

        r += 1
        ttk.Label(frm, text=i18n.t("API 地址：")).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=6)
        self.var_base = tk.StringVar(
            value=ai.get("base_url", "https://api.deepseek.com/v1"))
        ttk.Entry(frm, textvariable=self.var_base, width=42).grid(
            row=r, column=1, sticky="we", pady=6)

        r += 1
        ttk.Label(frm, text=i18n.t("模型：")).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=6)
        self.var_model = tk.StringVar(value=ai.get("model", "deepseek-chat"))
        ttk.Entry(frm, textvariable=self.var_model, width=42).grid(
            row=r, column=1, sticky="we", pady=6)

        r += 1
        ttk.Label(frm, text=i18n.t("API Key：")).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=6)
        self.var_key = tk.StringVar()
        ent = ttk.Entry(frm, textvariable=self.var_key, width=42, show="*")
        ent.grid(row=r, column=1, sticky="we", pady=6)
        if security.load_password("__ai__"):
            ttk.Label(frm, foreground="#888",
                      text=i18n.t("（已保存，留空沿用）")).grid(row=r, column=2,
                                                              padx=(4, 0))

        r += 1
        ttk.Label(frm, foreground="#888",
                  text=i18n.t("Key 经 Windows DPAPI 加密存储")).grid(
            row=r, column=1, sticky="w")
        r += 1
        ttk.Label(frm, foreground="#888",
                  text=i18n.t("示例：https://api.deepseek.com/v1")).grid(
            row=r, column=1, sticky="w")

        frm.columnconfigure(1, weight=1)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=14, pady=(0, 10))
        # 打开数据/日志文件夹：onemail.log 是排障唯一入口，给用户自助路径
        ttk.Button(btns, text=i18n.t("打开日志文件夹"),
                   command=self._open_data_dir).pack(side="left")
        ttk.Button(btns, text=i18n.t("取消"),
                   command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text=i18n.t("保存"),
                   command=self._save).pack(side="right")

    def _open_data_dir(self):
        from storage.config import data_dir
        try:
            os.startfile(data_dir())   # noqa: S606 Windows 专属项目
        except Exception:
            pass

    def _save(self):
        try:
            cfg = config_store.load()
            st = cfg.setdefault("settings", {})
            st["language"] = _LANG_BY_LABEL.get(self.cmb_lang.get(), "zh")
            # 主题下拉显示的是翻译后的标签；按当前选中索引反查主题键最稳妥
            theme_keys = list(_THEME_LABELS)
            st["theme"] = theme_keys[self.cmb_theme.current()]
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
        messagebox.showinfo(i18n.t("一邮通"),
                            i18n.t("设置已保存，语言/主题重启后生效。"),
                            parent=self)
        self.destroy()
