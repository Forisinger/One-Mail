# -*- coding: utf-8 -*-
"""v1.11.0 测试：强调色自定义（主题派生）、设置/账户界面的 i18n 与模块完整性。

不启动 Tk（CI/沙箱无桌面）：界面类只做导入与签名检查，颜色派生与配置
读写全部为纯函数 / 可隔离 IO，可离线断言。
"""
import ast
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from storage import config as config_store  # noqa: E402
from ui import i18n  # noqa: E402
from ui import theme as theme_mod  # noqa: E402

_HEX_RE = re.compile(r"^#[0-9a-f]{6}$")


class ThemeToolTests(unittest.TestCase):
    def test_normalize_hex(self):
        self.assertEqual(theme_mod.normalize_hex("#1E64DC"), "#1e64dc")
        self.assertEqual(theme_mod.normalize_hex("1e64dc"), "#1e64dc")
        self.assertEqual(theme_mod.normalize_hex("#abc"), "#aabbcc")
        for bad in ("", "  ", "red", "#12345", "#gggggg", None):
            self.assertEqual(theme_mod.normalize_hex(bad), "")

    def test_mix_endpoints_and_middle(self):
        self.assertEqual(theme_mod.mix("#000000", "#ffffff", 0.0), "#000000")
        self.assertEqual(theme_mod.mix("#000000", "#ffffff", 1.0), "#ffffff")
        self.assertEqual(theme_mod.mix("#000000", "#ffffff", 0.5), "#808080")
        # 非法输入不抛异常，原样返回第一个参数
        self.assertEqual(theme_mod.mix("bogus", "#ffffff", 0.5), "bogus")

    def test_derive_palette_invalid_accent_keeps_defaults(self):
        base = theme_mod.THEMES["light"]
        self.assertEqual(theme_mod.derive_palette("light", base, ""), base)
        self.assertEqual(theme_mod.derive_palette("light", base, "nope"), base)

    def test_derive_palette_light(self):
        base = theme_mod.THEMES["light"]
        c = theme_mod.derive_palette("light", base, "#ff0000")
        self.assertEqual(c["ACCENT"], "#ff0000")
        # 未读文字往黑里压、选中底往白里提
        self.assertEqual(c["ACCENT_DARK"], "#a60000")
        self.assertEqual(c["ACCENT_SOFT"], "#ffe0e0")
        self.assertEqual(c["BG"], base["BG"])   # 其余键不受影响

    def test_derive_palette_dark_brightens_unread_text(self):
        base = theme_mod.THEMES["dark"]
        c = theme_mod.derive_palette("dark", base, "#ff0000")
        self.assertTrue(_HEX_RE.match(c["ACCENT_DARK"]))
        self.assertTrue(_HEX_RE.match(c["ACCENT_SOFT"]))
        # 深色主题下未读文字必须比强调色更亮（否则深底上看不清）
        r, g, b = theme_mod._to_rgb(c["ACCENT_DARK"])
        self.assertGreater(g, 0)
        self.assertGreater(b, 0)
        self.assertNotEqual(c["ACCENT_DARK"], c["ACCENT"])


class ThemeConfigTests(unittest.TestCase):
    """强调色覆盖的读写（隔离 config 文件，不动用户真实配置）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = config_store._CONFIG
        config_store._CONFIG = os.path.join(self._tmp.name, "config.json")

    def tearDown(self):
        config_store._CONFIG = self._old
        self._tmp.cleanup()

    def test_default_when_no_override(self):
        self.assertEqual(theme_mod.accent_override("light"), "")
        self.assertEqual(theme_mod.effective_accent("light"),
                         theme_mod.default_accent("light"))
        self.assertEqual(theme_mod.colors()["ACCENT"],
                         theme_mod.THEMES["light"]["ACCENT"])

    def test_set_accent_applies_and_clears(self):
        self.assertTrue(theme_mod.set_accent("light", "#00aa55"))
        self.assertEqual(theme_mod.colors()["ACCENT"], "#00aa55")
        # 选中底色由强调了与白混 88% 派生
        self.assertEqual(theme_mod.colors()["ACCENT_SOFT"],
                         theme_mod.mix("#00aa55", "#ffffff", 0.88))
        # 恢复默认
        self.assertFalse(theme_mod.set_accent("light", ""))
        self.assertEqual(theme_mod.colors()["ACCENT"],
                         theme_mod.THEMES["light"]["ACCENT"])
        self.assertNotIn("theme_overrides", config_store.load()["settings"])

    def test_set_accent_rejects_invalid_value(self):
        theme_mod.set_accent("light", "#00aa55")
        self.assertFalse(theme_mod.set_accent("light", "not-a-color"))
        # 非法值等价于恢复默认，不落脏数据
        self.assertEqual(theme_mod.accent_override("light"), "")

    def test_accent_is_per_theme(self):
        config_store.save({"settings": {"theme": "dark"}})
        theme_mod.set_accent("light", "#00aa55")
        self.assertEqual(theme_mod.colors()["ACCENT"],
                         theme_mod.THEMES["dark"]["ACCENT"])   # dark 未覆盖
        theme_mod.set_accent("dark", "#123456")
        self.assertEqual(theme_mod.colors()["ACCENT"], "#123456")

    def test_damaged_overrides_do_not_break_colors(self):
        config_store.save({"settings": {
            "theme": "light", "theme_overrides": "not-a-dict"}})
        self.assertEqual(theme_mod.colors()["ACCENT"],
                         theme_mod.THEMES["light"]["ACCENT"])
        config_store.save({"settings": {
            "theme": "light", "theme_overrides": {"light": {"ACCENT": 123}}}})
        self.assertEqual(theme_mod.accent_override("light"), "")

    def test_unknown_theme_falls_back(self):
        config_store.save({"settings": {"theme": "solarized"}})
        self.assertEqual(theme_mod.current_theme(), theme_mod.DEFAULT_THEME)


class I18nV111Tests(unittest.TestCase):
    _NEW_KEYS = (
        "邮件管理", "⚙ 账户管理…", "账户管理…", "账户管理",
        "账户列表（双击编辑，Enter 编辑 / Delete 删除）", "显示名", "邮箱", "认证", "服务器", "状态",
        "已启用", "已停用", "启用 / 停用", "授权码", "＋ 新建",
        "请先选中一个账户", "账户已删除", "账户 {name} 已停用",
        "外观", "其他", "AI 功能", "强调色（重启生效）", "选择颜色…",
        "恢复默认", "默认：{color}", "主题与强调色在下次启动后生效。",
        "开机自启（用户级，无需管理员）",
        "同步已读到服务器（关闭后只改本地）",
        "开机自启设置失败（可能被安全软件拦截）",
    )

    def test_en_covers_v111_keys(self):
        i18n.init("en")
        try:
            for key in self._NEW_KEYS:
                self.assertNotEqual(i18n.t(key), key, f"缺英文翻译: {key}")
        finally:
            i18n.init("zh")

    def test_zh_returns_key_itself(self):
        i18n.init("zh")
        self.assertEqual(i18n.t("邮件管理"), "邮件管理")

    def test_no_duplicate_en_keys(self):
        """英文表不得有重复键（重复会静默覆盖，且说明有死键残留）。"""
        path = os.path.join(os.path.dirname(__file__), "..", "src", "ui", "i18n.py")
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and \
                    getattr(node.targets[0], "id", "") == "_EN":
                keys = [k.value for k in node.value.keys]
                dup = sorted({k for k in keys if keys.count(k) > 1})
                self.assertEqual(dup, [], f"_EN 存在重复键: {dup}")


def _has_tkinter() -> bool:
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:
        return False


class PaletteIntegrityTests(unittest.TestCase):
    """调色板完整性（v1.11.2）：深色主题下不得再有浅色控件残留。"""

    _REQUIRED = (
        "BG", "CARD", "TEXT", "GRAY", "ACCENT", "ACCENT_DARK", "ACCENT_SOFT",
        "ERR", "ROW_ALT", "DIVIDER", "HEADING", "BORDER", "SEL_FG",
        # ttk 控件面（缺一个就会有控件落到系统默认浅色）
        "FIELD", "BTN", "BTN_ACTIVE", "BTN_PRESSED", "TAB", "TROUGH", "DISABLED",
    )
    _DARK_SURFACES = ("BG", "CARD", "FIELD", "BTN", "BTN_ACTIVE", "BTN_PRESSED",
                      "TAB", "TROUGH", "HEADING", "ACCENT_SOFT")
    _LIGHT_SURFACES = ("BG", "CARD", "FIELD", "BTN", "TAB", "TROUGH", "HEADING")

    @staticmethod
    def _lum(color: str) -> float:
        r, g, b = theme_mod._to_rgb(color)
        return (r + g + b) / 3

    def test_both_themes_define_same_keys(self):
        self.assertEqual(set(theme_mod.THEMES["light"]),
                         set(theme_mod.THEMES["dark"]))

    def test_required_keys_present(self):
        for name, pal in theme_mod.THEMES.items():
            for key in self._REQUIRED:
                self.assertIn(key, pal, f"{name} 主题缺 {key}")

    def test_all_values_are_valid_hex(self):
        for name, pal in theme_mod.THEMES.items():
            for key, val in pal.items():
                self.assertEqual(theme_mod.normalize_hex(val), val.lower(),
                                 f"{name}.{key}={val} 不是规范 #rrggbb")

    def test_dark_theme_surfaces_are_dark(self):
        pal = theme_mod.THEMES["dark"]
        for key in self._DARK_SURFACES:
            self.assertLess(self._lum(pal[key]), 95,
                            f"dark.{key}={pal[key]} 太亮（会像浅色主题）")
        self.assertGreater(self._lum(pal["TEXT"]), 150, "dark.TEXT 不够亮")
        self.assertGreater(self._lum(pal["GRAY"]), 90, "dark.GRAY 不够亮")

    def test_light_theme_surfaces_are_light(self):
        pal = theme_mod.THEMES["light"]
        for key in self._LIGHT_SURFACES:
            self.assertGreater(self._lum(pal[key]), 200,
                               f"light.{key}={pal[key]} 太暗")
        self.assertLess(self._lum(pal["TEXT"]), 110, "light.TEXT 不够深")

    def test_text_contrast_on_each_surface(self):
        """文字与各控件面的亮度差要够（否则深色主题里会出现"看不见的字"）。"""
        for name, pal in theme_mod.THEMES.items():
            for surface in ("BG", "CARD", "FIELD", "BTN", "TAB"):
                diff = abs(self._lum(pal["TEXT"]) - self._lum(pal[surface]))
                self.assertGreater(diff, 80, f"{name}: TEXT 与 {surface} 对比不足")

    def test_accent_override_keeps_extended_keys(self):
        """强调色覆盖后，新增的控件面键必须原样保留（不能被覆盖逻辑吃掉）。"""
        base = dict(theme_mod.THEMES["dark"])
        out = theme_mod.derive_palette("dark", base, "#ff0000")
        for key in self._REQUIRED:
            self.assertIn(key, out, f"覆盖强调色后丢了 {key}")
        self.assertEqual(out["FIELD"], base["FIELD"])
        self.assertEqual(out["BTN"], base["BTN"])


class ModuleShapeTests(unittest.TestCase):
    """界面模块结构检查（源码级，不依赖 tkinter / 不实例化 Tk）。"""

    @staticmethod
    def _src(name: str) -> str:
        path = os.path.join(os.path.dirname(__file__), "..", "src", "ui", name)
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_accounts_dialog_shape(self):
        text = self._src("accounts_dialog.py")
        self.assertIn("class AccountsDialog", text)
        for name in ("add_account", "edit_account", "remove_account",
                     "toggle_enabled", "preselect"):
            self.assertIn(name, text, f"缺少 {name}")
        # 删账户必须先停线程再删库（幽灵邮件防线）
        self.assertLess(text.index("scheduler.stop_account"),
                        text.index("db.delete_account_mails"))

    def test_settings_dialog_has_tabs(self):
        text = self._src("settings_dialog.py")
        self.assertIn("ttk.Notebook", text)
        for key in ("外观", "AI 功能", "其他"):
            self.assertIn(f'text=i18n.t("{key}")', text)
        # 强调色走主题模块的覆盖通道，不直接写色板
        self.assertIn("theme_mod.set_accent", text)

    def test_main_window_has_account_manager_entry(self):
        text = self._src("main_window.py")
        self.assertIn("def open_account_manager", text)
        self.assertIn("def _on_account_removed", text)
        # 顶栏不再直接放置账户增删改按钮
        self.assertNotIn("self.add_account", text)
        self.assertNotIn("self.edit_account", text)
        self.assertNotIn("self.remove_account", text)
        # 左栏标题已改为「邮件管理」
        self.assertIn('i18n.t("邮件管理")', text)
        # 邮件列表右键菜单里不再有"新建文件夹…"（该功能已移入邮件管理栏）
        menu = text[text.index("def _mail_list_menu"):
                    text.index("def delete_selected_mail")]
        self.assertNotIn("新建文件夹…", menu)
        # 文件夹分区仍保留新建入口
        self.assertIn("def create_folder", text)
        self.assertIn("def _folder_menu", text)

    def test_ttk_style_covers_all_widgets(self):
        """v1.11.2：所有 ttk 控件类都必须在 _setup_style 里显式着色。"""
        text = self._src("main_window.py")
        body = text[text.index("def _setup_style"):text.index("def _tr_status")]
        for name in ("TButton", "TEntry", "TSpinbox", "TCombobox",
                     "TCheckbutton", "TRadiobutton", "TNotebook",
                     "TNotebook.Tab", "TScrollbar", "Treeview",
                     "Treeview.Heading", "TFrame", "TLabel", "TPanedwindow",
                     "Sash", "TSeparator", "TLabelframe"):
            self.assertIn(f'"{name}"', body, f"_setup_style 未配置 {name}")
        # 原生主题无法着色：必须切到 clam
        self.assertIn('theme_use("clam")', body)
        # 没有 ttk.Style 通道的两类控件走 option database
        self.assertIn("*Menu.background", body)
        self.assertIn("*TCombobox*Listbox.background", body)

    def test_main_window_resize_guards(self):
        """缩放保护（v1.11.1）：邮件列表不得在缩放后被挤成 0 高度/被裁掉。"""
        text = self._src("main_window.py")
        self.assertIn('self.root.bind("<Configure>"', text)
        for name in ("_on_root_configure", "_after_resize",
                     "_ensure_pane_minimums", "_autofit_columns"):
            self.assertIn(f"def {name}", text, f"缺少 {name}")
        # 列宽与分栏计算已抽到与 tkinter 无关的 layout 模块（可离线单测）
        self.assertIn("from .layout import", text)
        self.assertIn("minwidth=COL_MIN[", text)
        # 邮件列表/阅读区不再用 Treeview 默认 10 行、Text 默认 24 行：
        # 两个默认请求高度之和超过最小窗口，会把对面一栏挤没
        self.assertIn("height=6", text)
        self.assertIn("height=8", text)


@unittest.skipUnless(_has_tkinter(), "tkinter 不可用（无桌面环境），跳过真实导入检查")
class TkImportTests(unittest.TestCase):
    def test_ui_modules_importable(self):
        from ui.accounts_dialog import AccountsDialog
        from ui.settings_dialog import SettingsDialog
        self.assertTrue(callable(AccountsDialog))
        self.assertTrue(callable(SettingsDialog))


if __name__ == "__main__":
    unittest.main()
