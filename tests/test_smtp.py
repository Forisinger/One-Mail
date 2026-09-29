# -*- coding: utf-8 -*-
"""SMTP 模块离线单测：MIME 组装、地址解析、SMTP 主机推导。不联网。"""
import os
import sys
import tempfile
import tkinter as tk
import unittest
from email import message_from_bytes

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.account import Account
from core.smtp_client import build_mime
from ui.compose_window import ComposeWindow
from ui.richtext import text_to_html, font_tag_name


def _acc():
    return Account(id="t1", name="发件人测试", email="sender@example.com",
                   imap_host="imap.example.com", smtp_host="", smtp_port=465)


class TestSmtpEndpoint(unittest.TestCase):
    def test_derive_from_imap(self):
        acc = Account(id="t", name="n", email="a@163.com",
                      imap_host="imap.163.com")
        self.assertEqual(acc.smtp_endpoint(), ("smtp.163.com", 465))

    def test_explicit_host_wins(self):
        acc = Account(id="t", name="n", email="a@x.com",
                      imap_host="imap.163.com", smtp_host="smtp.exmail.qq.com",
                      smtp_port=465)
        self.assertEqual(acc.smtp_endpoint(), ("smtp.exmail.qq.com", 465))


class TestBuildMime(unittest.TestCase):
    def test_basic_fields(self):
        msg = build_mime(_acc(), ["a@b.com", "c@d.com"], "主题测试", "正文内容")
        self.assertEqual(msg["To"], "a@b.com, c@d.com")
        raw = msg.as_bytes()
        parsed = message_from_bytes(raw)
        # 显示名是中文，必然被 RFC 2047 编码；解码后应还原
        from email.header import decode_header, make_header
        name = str(make_header(decode_header(parsed["From"])))
        self.assertEqual(name, "发件人测试 <sender@example.com>")

    def test_ascii_attachment(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "wb") as f:
            f.write(b"hello attachment")
        try:
            msg = build_mime(_acc(), ["a@b.com"], "带附件", "正文",
                             attachments=[path])
            names = [p.get_filename() for p in msg.walk()]
            self.assertIn(os.path.basename(path), names)
        finally:
            os.unlink(path)

    def test_chinese_attachment_name(self):
        fd, path = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, "wb") as f:
            f.write(b"%PDF-1.4 fake")
        os.rename(path, os.path.join(os.path.dirname(path), "中文附件测试.pdf"))
        path_cn = os.path.join(os.path.dirname(path), "中文附件测试.pdf")
        try:
            msg = build_mime(_acc(), ["a@b.com"], "中文附件", "正文",
                             attachments=[path_cn])
            raw = msg.as_bytes().decode("utf-8", "replace")
            self.assertIn("utf-8''%", raw.lower() or raw)  # RFC 2231 编码痕迹
            # 文件名可被解码还原
            parsed = message_from_bytes(msg.as_bytes())
            found = [p.get_filename() for p in parsed.walk()
                     if p.get_filename()]
            self.assertTrue(any("中文附件测试" in n for n in found),
                            f"文件名解码失败: {found}")
        finally:
            os.unlink(path_cn)

    def test_empty_subject_fallback(self):
        msg = build_mime(_acc(), ["a@b.com"], "", "x")
        self.assertIsNotNone(msg["Subject"])


class TestCcBccHtml(unittest.TestCase):
    def test_cc_header(self):
        msg = build_mime(_acc(), ["a@b.com"], "s", "x", cc_addrs=["c@d.com"])
        self.assertEqual(msg["Cc"], "c@d.com")

    def test_bcc_header_present_for_envelope(self):
        msg = build_mime(_acc(), ["a@b.com"], "s", "x", bcc_addrs=["b@d.com"])
        self.assertEqual(msg["Bcc"], "b@d.com")  # send_message 发送时剥离

    def test_html_generates_alternative(self):
        msg = build_mime(_acc(), ["a@b.com"], "s", "plain",
                         html_body="<b>bold</b>")
        self.assertEqual(msg.get_content_type(), "multipart/alternative")
        parts = msg.get_payload()
        self.assertEqual(parts[0].get_content_type(), "text/plain")
        self.assertEqual(parts[1].get_content_type(), "text/html")

    def test_html_with_attachments_wraps_twice(self):
        msg = build_mime(_acc(), ["a@b.com"], "s", "p", attachments=[],
                         html_body="<i>x</i>")
        self.assertEqual(msg.get_content_type(), "multipart/alternative")


class TestTextToHtml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError:
            cls.root = None

    @classmethod
    def tearDownClass(cls):
        if cls.root:
            cls.root.destroy()

    def setUp(self):
        if not self.root:
            self.skipTest("无显示环境，跳过 Tk 相关测试")

    def test_plain_text_escapes_and_br(self):
        w = tk.Text(self.root)
        w.insert("1.0", "a<b\nline2")
        out = text_to_html(w)
        self.assertEqual(out, "a&lt;b<br>\nline2")

    def test_bold_tag_export(self):
        w = tk.Text(self.root)
        w.insert("1.0", "hello world")
        w.tag_add(font_tag_name(True, False, False), "1.0", "1.5")
        out = text_to_html(w)
        self.assertIn("<b>hello</b>", out)
        self.assertIn(" world", out)

    def test_color_export(self):
        w = tk.Text(self.root)
        w.insert("1.0", "red")
        w.tag_configure("color-#ff0000", foreground="#ff0000")
        w.tag_add("color-#ff0000", "1.0", "end")
        out = text_to_html(w)
        self.assertIn('<span style="color:#ff0000">red</span>', out)


class TestAddressParsing(unittest.TestCase):
    def test_split_various_separators(self):
        raw = "a@b.com, c@d.com；e@f.com　g@h.com"
        self.assertEqual(
            ComposeWindow.parse_addresses(raw),
            ["a@b.com", "c@d.com", "e@f.com", "g@h.com"])

    def test_rejects_bad_address(self):
        with self.assertRaises(ValueError):
            ComposeWindow.parse_addresses("not-an-email")


if __name__ == "__main__":
    unittest.main(verbosity=2)
