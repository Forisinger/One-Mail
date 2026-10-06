# -*- coding: utf-8 -*-
"""v1.11.4 回归测试：多 agent 审查修复轮。

覆盖：
1. htmltext 不再吞掉内联标签之间的独立空格（P1，此前 world again → worldagain）
2. smtp_auth 334 拒绝路径 bytes 拼接修复（此前必抛 TypeError，真实原因丢失）
3. flag_sync 非法 UID 去重键即时释放（键泄漏红线）
4. OAuth2 回调仅接受带 code/error 的请求（favicon 杂散 GET 不再覆盖结果）
"""
import base64
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.flag_sync import FlagSync  # noqa: E402
from core.oauth2 import OAuth2Error, _CallbackHandler, smtp_auth  # noqa: E402


# ---------- 1. htmltext 空格保留 ----------

class HtmlTextSpace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import tkinter as tk
            cls.tk = tk
            cls.root = tk.Tk()
            cls.root.withdraw()
        except Exception:
            cls.root = None   # 无显示环境：跳过渲染测试

    @classmethod
    def tearDownClass(cls):
        if cls.root is not None:
            cls.root.destroy()

    def _render(self, html: str) -> str:
        from ui.htmltext import render_html
        txt = self.tk.Text(self.root)
        render_html(txt, html, ("Arial", 10),
                    {"ACCENT": "#1e64dc", "TEXT": "#000"})
        out = txt.get("1.0", "end")
        txt.destroy()
        return out

    def test_inline_tag_space_kept(self):
        """<b>x</b> <i>y</i> 之间的独立空格不得吞掉（P1 回归）。"""
        if self.root is None:
            self.skipTest("无 Tk 显示环境")
        out = self._render("Hello <b>world</b> <i>again</i> end")
        self.assertIn("world again", out)
        self.assertNotIn("worldagain", out)

    def test_cjk_newline_still_folded(self):
        """CJK 间换行仍折叠为无空格（v1.10.1 行为不回归）。"""
        if self.root is None:
            self.skipTest("无 Tk 显示环境")
        out = self._render("<b>加粗</b>\n<i>斜体</i>")
        self.assertIn("加粗斜体", out)

    def test_block_indent_still_dropped(self):
        """块级标签之间的换行缩进仍不插入。"""
        if self.root is None:
            self.skipTest("无 Tk 显示环境")
        out = self._render("<p>a</p>\n  <p>b</p>")
        self.assertIn("a", out)
        self.assertIn("b", out)
        self.assertNotIn(" \n  \n", out)


# ---------- 2. smtp_auth 334 拒绝路径 ----------

class _FakeSmtp:
    def __init__(self, code, resp):
        self._ret = (code, resp)
        self.cmds = []

    def docmd(self, *args):
        self.cmds.append(args)
        return self._ret


class SmtpAuth334(unittest.TestCase):
    def test_334_rejection_decodes_base64_challenge(self):
        """334 + base64 JSON 挑战：抛 OAuth2Error 且携带服务器错误详情。"""
        err = {"status": "400", "schemes": "Bearer",
               "scope": "https://outlook.office.com/SMTP.Send"}
        srv = _FakeSmtp(334, base64.b64encode(json.dumps(err).encode()))
        acc = SimpleNamespace(email="u@x.com")
        with self.assertRaises(OAuth2Error) as cm:
            smtp_auth(srv, acc, "tok")
        self.assertIn("SMTP 认证被拒", str(cm.exception))
        self.assertIn("SMTP.Send", str(cm.exception))   # 真实原因可见

    def test_334_non_base64_no_typeerror(self):
        """334 + 非 base64 挑战：不再抛 TypeError（bytes+str 拼接已修）。"""
        srv = _FakeSmtp(334, b"\xff garbage not base64 !!")
        acc = SimpleNamespace(email="u@x.com")
        with self.assertRaises(OAuth2Error):
            smtp_auth(srv, acc, "tok")

    def test_235_success(self):
        srv = _FakeSmtp(235, b"2.7.0 Accepted")
        acc = SimpleNamespace(email="u@x.com")
        smtp_auth(srv, acc, "tok")   # 不抛即通过


# ---------- 3. flag_sync 非法 UID 键释放 ----------

def _account(acc_id="a1"):
    return SimpleNamespace(id=acc_id, email=f"{acc_id}@x.com",
                           imap_host="imap.x.com", imap_port=993, ssl=True)


class FlagSyncBadUidKeyRelease(unittest.TestCase):
    def _make(self, *jobs):
        calls = []

        def connector(account, password, folder, uids, seen):
            calls.append(list(uids))

        fs = FlagSync(lambda aid: (_account(aid), "pwd"),
                      connector=connector, enabled=lambda: True,
                      log=lambda m: None, start_thread=False)
        # 先经 submit_many 真正填入去重键——否则 _pending 为空，
        # assertNotIn 恒真，测不出键泄漏（假阳性，v1.11.4 复审修正）
        if jobs:
            fs.submit_many(list(jobs))
        return fs, calls

    def test_mixed_batch_releases_bad_keys(self):
        """数字+非法 UID 混批：非法键也必须释放，不得永久拦截后续同步。"""
        fs, calls = self._make(("a1", "INBOX", "12", True),
                               ("a1", "INBOX", "abc", True))
        self.assertIn(("a1", "INBOX", "abc", True), fs._pending)  # 前置成立
        try:
            fs._process_batch([("a1", "INBOX", "12", True, 0),
                               ("a1", "INBOX", "abc", True, 0)])
            # connector 只收到数字 UID
            self.assertEqual(calls, [["12"]])
            # 非法 UID 的去重键已释放（键泄漏红线）
            self.assertNotIn(("a1", "INBOX", "abc", True), fs._pending)
        finally:
            fs.stop()

    def test_bad_uid_only_batch_still_released(self):
        """整批非法 UID：全部释放，不调 connector。"""
        fs, calls = self._make(("a1", "INBOX", "xyz", False))
        try:
            fs._process_batch([("a1", "INBOX", "xyz", False, 0)])
            self.assertEqual(calls, [])
            self.assertNotIn(("a1", "INBOX", "xyz", False), fs._pending)
        finally:
            fs.stop()

    def test_resubmit_after_bad_uid_reaches_connector(self):
        """同一非法 UID 再次提交：不再被去重键拦截（可直接重测）。"""
        fs, calls = self._make(("a1", "INBOX", "bad", True))
        try:
            for _ in range(2):
                fs._process_batch([("a1", "INBOX", "bad", True, 0)])
            self.assertEqual(calls, [])   # 非法 UID 永不进 connector，但键不残留
            self.assertNotIn(("a1", "INBOX", "bad", True), fs._pending)
        finally:
            fs.stop()


# ---------- 4. OAuth2 回调防御 ----------

class CallbackGuard(unittest.TestCase):
    def setUp(self):
        self.srv = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
        self.srv.result = {}
        self.srv.done = threading.Event()
        self.t = threading.Thread(
            target=self.srv.serve_forever, kwargs={"poll_interval": 0.05},
            daemon=True)
        self.t.start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def _get(self, path):
        try:
            urllib.request.urlopen(self.base + path, timeout=3).read()
            return None
        except urllib.error.HTTPError as e:
            return e.code

    def test_favicon_does_not_override_result(self):
        """无参 GET（favicon 等）返回 404，不覆盖 result、不置位 done。"""
        self.assertEqual(self._get("/favicon.ico"), 404)
        self.assertEqual(self.srv.result, {})
        self.assertFalse(self.srv.done.is_set())

    def test_code_callback_still_accepted(self):
        """带 code 的正常回调仍被接受并置位 done。"""
        self._get("/favicon.ico")   # 杂散请求先行
        self._get("/?code=abc&state=s1")
        self.assertTrue(self.srv.done.is_set())
        self.assertEqual(self.srv.result.get("code"), "abc")
        self.assertEqual(self.srv.result.get("state"), "s1")

    def test_error_callback_accepted(self):
        """带 error 的回调也置位 done（授权被用户拒绝的正常路径）。"""
        self._get("/?error=access_denied")
        self.assertTrue(self.srv.done.is_set())
        self.assertEqual(self.srv.result.get("error"), "access_denied")


if __name__ == "__main__":
    unittest.main(verbosity=1)
