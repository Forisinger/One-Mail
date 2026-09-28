# -*- coding: utf-8 -*-
"""解析器与数据层单元测试（不依赖网络）。"""
import base64
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.parser import parse_raw, _HTML2Text
from core.account import Account


def _gbk_word(text: str) -> str:
    """生成 RFC2047 GBK 编码词，保证测试数据本身正确。"""
    b64 = base64.b64encode(text.encode("gbk")).decode()
    return f"=?gbk?B?{b64}?="


class TestParser(unittest.TestCase):
    def test_gbk_plain_mail(self):
        raw = (
            f"From: {_gbk_word('张三丰')} <zhangsan@example.com>\r\n"
            f"To: me@qq.com\r\n"
            f"Subject: {_gbk_word('下午开会')}\r\n"
            f"Date: Mon, 28 Sep 2026 10:00:00 +0800\r\n"
            f"Message-ID: <abc@example.com>\r\n"
            f"Content-Type: text/plain; charset=gbk\r\n\r\n"
        ).encode("ascii") + "这是正文内容，测试 GBK 编码。".encode("gbk")
        m = parse_raw(raw)
        self.assertEqual(m.from_addr, "zhangsan@example.com")
        self.assertEqual(m.from_name, "张三丰")
        self.assertIn("GBK 编码", m.body_text)
        self.assertIn("下午开会", m.subject)
        self.assertEqual(m.message_id, "<abc@example.com>")
        self.assertIn("2026-09-28", m.received_at)

    def test_html_mail_with_attachment(self):
        html = "<html><head><style>.x{color:red}</style></head>" \
               "<body><p>Hello <b>World</b></p><br>Second line<script>evil()</script></body></html>"
        raw = (
            f"From: Lisi <lisi@a.com>\r\nSubject: HTML test\r\n"
            f"MIME-Version: 1.0\r\n"
            f"Content-Type: multipart/mixed; boundary=BOUND\r\n\r\n"
            f"--BOUND\r\nContent-Type: text/html; charset=utf-8\r\n\r\n{html}\r\n"
            f"--BOUND\r\nContent-Type: application/pdf; name=report.pdf\r\n"
            f"Content-Disposition: attachment; filename=report.pdf\r\n\r\nDATA\r\n"
            f"--BOUND--"
        ).encode("utf-8")
        m = parse_raw(raw)
        self.assertIn("Hello World", m.body_text)
        self.assertNotIn("evil()", m.body_text)
        self.assertEqual(m.attachment_names, ["report.pdf"])

    def test_garbage_never_crashes(self):
        for junk in (b"", b"\x00\xff\xfe garbage", b"From: broken", b"Content-Type: text/plain\r\n\r\n\xfe\xff"):
            m = parse_raw(junk)
            self.assertIsInstance(m.subject, str)
            self.assertIsInstance(m.body_text, str)


class TestHtml2Text(unittest.TestCase):
    def test_strip(self):
        p = _HTML2Text()
        p.feed("<div>a<br>b</div><p>c</p>")
        self.assertIn("a\nb", p.text())
        self.assertIn("c", p.text())


class TestAccountGuess(unittest.TestCase):
    def test_known_hosts(self):
        self.assertEqual(Account.guess_host("a@qq.com"), ("imap.qq.com", 993))
        self.assertEqual(Account.guess_host("a@163.com"), ("imap.163.com", 993))
        host, _ = Account.guess_host("a@custom.cn")
        self.assertEqual(host, "imap.custom.cn")


if __name__ == "__main__":
    unittest.main(verbosity=2)
