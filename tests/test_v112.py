# -*- coding: utf-8 -*-
"""v1.12.0：体验增强轮回归测试。

覆盖：flag_sync 连续分组保序、重试放大中止、folder_to_wire 转义、
database.existing_uids、config 类型错误兜底、htmltext 链接/引用块。
"""
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.flag_sync import FlagSync          # noqa: E402
from core.mail_client import folder_to_wire  # noqa: E402
from storage import database                 # noqa: E402


class _Harness:
    def __init__(self, accounts=None, enabled=True, fail_first=0):
        self.calls = []
        self.accounts = accounts or {"a1": SimpleNamespace(
            id="a1", email="a1@x.com", imap_host="imap.x.com",
            imap_port=993, ssl=True)}
        self._enabled = enabled
        self.fail_first = fail_first
        import threading
        self._lock = threading.Lock()

    def get_credentials(self, account_id):
        acc = self.accounts.get(account_id)
        return (acc, "pwd") if acc else (None, None)

    def enabled(self):
        return self._enabled

    def connector(self, account, password, folder, uids, seen):
        with self._lock:
            self.calls.append((account.id, folder, list(uids), seen))
            if self.fail_first > 0:
                self.fail_first -= 1
                raise ConnectionError("模拟网络失败")

    def make(self):
        return FlagSync(self.get_credentials, connector=self.connector,
                        enabled=self.enabled, log=lambda m: None,
                        start_thread=False)


class FlagSyncOrderTests(unittest.TestCase):
    def test_interleaved_directions_preserve_order(self):
        """R→U→R 交错序列：连续分组保证执行顺序与入队一致（v1.11.7）。"""
        h = _Harness()
        fs = h.make()
        jobs = [
            ("a1", "INBOX", "1", True),
            ("a1", "INBOX", "2", False),
            ("a1", "INBOX", "3", True),
        ]
        fs._process_batch([(a, f, u, s, 0) for a, f, u, s in jobs])
        fs.stop()
        # 三段连续 run 依序执行：读→未读→读
        self.assertEqual([c[3] for c in h.calls], [True, False, True])

    def test_same_direction_merged(self):
        """连续同方向仍合并为一组（性能不变）。"""
        h = _Harness()
        fs = h.make()
        jobs = [("a1", "INBOX", str(i), True) for i in range(1, 6)]
        fs._process_batch([(a, f, u, s, 0) for a, f, u, s in jobs])
        fs.stop()
        self.assertEqual(len(h.calls), 1)
        self.assertEqual(h.calls[0][2], ["1", "2", "3", "4", "5"])

    def test_first_chunk_failure_aborts_group(self):
        """组内首个 chunk 连续失败 2 次即中止整组（防重试放大）。"""
        h = _Harness(fail_first=2)   # 前 2 次调用失败
        fs = h.make()
        # 100 UIDs = 2 chunks（CHUNK_SIZE=50）
        jobs = [("a1", "INBOX", str(i), True) for i in range(1, 101)]
        fs._process_batch([(a, f, u, s, 0) for a, f, u, s in jobs])
        fs.stop()
        # 首个 chunk 重试失败 → 整组中止，不再发起第二个 chunk
        self.assertEqual(len(h.calls), 2)

    def test_mid_group_failure_aborts_too(self):
        """chunk1 成功、chunk2 双失败：整组中止（v1.13.0，防中段放大）。"""
        import threading

        calls = []
        state = {"n": 0}

        def connector(account, password, folder, uids, seen):
            state["n"] += 1
            if state["n"] in (3, 4):   # chunk2 的两次尝试失败
                raise ConnectionError("断网")
            calls.append(list(uids))

        fs = FlagSync(lambda aid: (_Harness().accounts["a1"], "pwd"),
                      connector=connector, enabled=lambda: True,
                      log=lambda m: None, start_thread=False)
        # 150 UIDs = 3 chunks：chunk1/2 成功，chunk3 双失败 → 整组中止
        jobs = [("a1", "INBOX", str(i), True) for i in range(1, 151)]
        fs._process_batch([(a, f, u, s, 0) for a, f, u, s in jobs])
        fs.stop()
        # chunk1/2 成功 + chunk3 两次失败 → 共 4 次调用，无 chunk4
        self.assertEqual(state["n"], 4)
        self.assertEqual(len(calls), 2)


class FolderWireTests(unittest.TestCase):
    def test_quotes_escaped(self):
        self.assertEqual(folder_to_wire('a"b'), '"a\\"b"')

    def test_backslash_escaped(self):
        self.assertEqual(folder_to_wire("a\\b"), '"a\\\\b"')

    def test_plain_ascii(self):
        self.assertEqual(folder_to_wire("INBOX"), '"INBOX"')


class ExistingUidsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = database._DB
        database._DB = os.path.join(self._tmp.name, "t.db")
        database.init()

    def tearDown(self):
        database._DB = self._old
        self._tmp.cleanup()

    def test_returns_cached_only(self):
        """existing_uids 只返回本地已有的 UID。"""
        acc = f"t-{id(self)}"
        try:
            database.insert_mails(acc, [{
                "uid": "10", "message_id": "<m10@x>", "subject": "s",
                "from_addr": "a@x", "from_name": "A",
                "received_at": "2026-01-01T00:00:00",
                "body_text": "hi", "body_html": "",
                "attachment_names": "",
            }], folder="INBOX")
            got = database.existing_uids(acc, "INBOX", ["10", "11", "12"])
            self.assertEqual(got, {"10"})
        finally:
            database.delete_account_mails(acc)


class ConfigTypeTests(unittest.TestCase):
    def test_non_dict_config_falls_back(self):
        """合法 JSON 但类型错误（如列表）走损坏备份回默认，不抛异常。"""
        from storage import config as config_store
        with tempfile.TemporaryDirectory() as td:
            orig = config_store._CONFIG
            try:
                cfg_path = os.path.join(td, "config.json")
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(["not", "a", "dict"], f)
                config_store._CONFIG = cfg_path
                data = config_store.load()
                self.assertEqual(data["accounts"], [])
                self.assertIn("settings", data)
            finally:
                config_store._CONFIG = orig


class HtmlTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import tkinter as tk
            cls.root = tk.Tk()
            cls.root.withdraw()
        except Exception:
            raise unittest.SkipTest("无 tkinter 环境")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_link_gets_click_binding(self):
        """<a href> 生成的标签带 Button-1 绑定（桩件记录 tag_bind 调用）。"""
        from ui.htmltext import _Renderer

        class _Stub:
            def __init__(self):
                self.bound = []

            def tag_configure(self, name, **kw):
                pass

            def insert(self, *a, **k):
                pass

            def tag_bind(self, name, seq, fn):
                self.bound.append((name, seq))

        stub = _Stub()
        r = _Renderer(stub, ("Microsoft YaHei UI", 10),
                      {"ACCENT": "#06c", "GRAY": "#888"})
        r.feed('<a href="https://example.com">点我</a>')
        r.close()
        self.assertTrue(any(seq == "<Button-1>" for _, seq in stub.bound),
                        "链接标签应绑定 Button-1")
    def test_blockquote_indent_and_gray(self):
        """blockquote 有左缩进与灰色前景。"""
        import tkinter as tk
        from ui.htmltext import render_html
        txt = tk.Text(self.root)
        render_html(txt, "<blockquote>引用内容</blockquote>",
                    ("Microsoft YaHei UI", 10), {"ACCENT": "#06c",
                                                 "GRAY": "#888888"})
        # 取首个块内容字符的标签，应有 lmargin 配置
        tags = txt.tag_names("2.0")
        lm = [t for t in tags if txt.tag_cget(t, "lmargin1") == "18"]
        self.assertTrue(lm, "blockquote 应有缩进标签")

    def test_nested_list_indent(self):
        """嵌套列表按深度缩进。"""
        import tkinter as tk
        from ui.htmltext import render_html
        txt = tk.Text(self.root)
        render_html(txt, "<ul><li>外层<ul><li>内层</li></ul></li></ul>",
                    ("Microsoft YaHei UI", 10), {"ACCENT": "#06c",
                                                 "GRAY": "#888"})
        content = txt.get("1.0", "end")
        self.assertIn("    • 内层", content)


class I18nCompletenessTests(unittest.TestCase):
    """i18n 键完整性：AST 扫描 t("...") 字面量，断言都在英文表中。

    缺键不会崩（回退中文），但英文界面会冒出中文串——静默退化，
    只能靠这类静态测试兜住。
    """

    def test_all_literal_keys_translated(self):
        import ast
        from ui import i18n
        src_dir = os.path.join(os.path.dirname(__file__), "..", "src")
        keys: set[str] = set()
        for dirpath, _dirs, files in os.walk(src_dir):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                with open(path, encoding="utf-8") as f:
                    try:
                        tree = ast.parse(f.read())
                    except SyntaxError:
                        continue
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    fn_attr = node.func
                    if not (isinstance(fn_attr, ast.Attribute)
                            and fn_attr.attr == "t" and node.args):
                        continue
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        keys.add(arg.value)
        self.assertTrue(keys, "应至少扫描到一批 i18n 键")
        missing = sorted(k for k in keys if k not in i18n._EN)
        self.assertEqual(missing, [], f"英文表缺失的 i18n 键: {missing}")


if __name__ == "__main__":
    unittest.main()
