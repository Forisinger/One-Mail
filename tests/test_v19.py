# -*- coding: utf-8 -*-
"""v1.9.0 新功能测试：body_html 富文本 / 本地文件夹 / AI 客户端 / i18n。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.parser import parse_raw  # noqa: E402
from core import ai_client  # noqa: E402
from storage import database as db  # noqa: E402
from ui import i18n  # noqa: E402


def _html_mail(body_html: str, plain: str = "") -> bytes:
    parts = []
    if plain:
        parts.append(
            "Content-Type: text/plain; charset=utf-8\r\n\r\n" + plain)
    parts.append(
        "Content-Type: text/html; charset=utf-8\r\n\r\n" + body_html)
    boundary = "bnd42"
    head = (
        "From: =?utf-8?B?5byg5LiJ?= <hong@example.com>\r\n"
        "To: me@qq.com\r\nSubject: rich\r\n"
        "Date: Mon, 28 Sep 2026 10:00:00 +0800\r\n"
        f"Content-Type: multipart/alternative; boundary=\"{boundary}\"\r\n\r\n")
    body = ("\r\n").join(
        f"--{boundary}\r\n{p}" for p in parts) + f"\r\n--{boundary}--\r\n"
    return head.encode("utf-8") + body.encode("utf-8")


class BodyHtmlTests(unittest.TestCase):
    def test_html_only_mail_keeps_body_html(self):
        m = parse_raw(_html_mail("<b>你好</b> <font color='#ff0000'>红</font>"))
        self.assertIn("<b>你好</b>", m.body_html)
        self.assertIn("红", m.body_text)          # 纯文本兜底仍有效
        self.assertNotIn("<b>", m.body_text)

    def test_multipart_plain_and_html(self):
        m = parse_raw(_html_mail("<i>hi</i>", plain="plain hi"))
        self.assertEqual(m.body_text.strip(), "plain hi")
        self.assertIn("<i>hi</i>", m.body_html)

    def test_plain_only_mail_no_html(self):
        m = parse_raw(_html_mail("", plain="just text"))
        self.assertEqual(m.body_html, "")

    def test_insert_and_roundtrip(self):
        """body_html 经 insert_mails 入库后能原样读回。"""
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db, db._DB = db._DB, os.path.join(self._tmp.name, "t.db")
        try:
            db.init()
            m = parse_raw(_html_mail("<b>x</b>"))
            new = db.insert_mails("a1", [{
                "uid": "1", "message_id": "<r1@x>", "subject": "s",
                "from_addr": "a@b", "from_name": "A",
                "received_at": "2026-09-30 10:00:00",
                "body_text": m.body_text, "body_html": m.body_html,
                "attachment_names": [],
            }])
            self.assertEqual(len(new), 1)
            row = db.get_mail(1)
            self.assertEqual(row["body_html"], "<b>x</b>")
            self.assertEqual(row["local_folder"], "")
        finally:
            db._DB = self._old_db
            self._tmp.cleanup()


class LocalFolderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db, db._DB = db._DB, os.path.join(self._tmp.name, "t.db")
        db.init()
        db.insert_mails("a1", [
            {"uid": str(i), "message_id": f"<{i}@x>", "subject": f"s{i}",
             "from_addr": "a@b", "from_name": "A",
             "received_at": "2026-09-30 10:00:00", "body_text": "b",
             "body_html": "", "attachment_names": []} for i in range(1, 6)])

    def tearDown(self):
        db._DB = self._old_db
        self._tmp.cleanup()

    def test_move_and_counts(self):
        db.set_mail_local_folder(1, "工作")
        rows, _ = db.search_mails(local_folder="工作")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 1)
        rows, _ = db.search_mails(local_folder="")
        self.assertEqual(len(rows), 4)
        counts = db.local_folder_counts()
        self.assertEqual(counts.get("工作"), (1, 1))
        self.assertEqual(counts.get("", (0, 0))[0], 4)

    def test_move_keeps_server_folder(self):
        db.set_mail_local_folder(2, "工作")
        row = db.get_mail(2)
        self.assertEqual(row["folder"], "INBOX")   # 服务器来源文件夹不变
        self.assertEqual(row["local_folder"], "工作")

    def test_move_back_via_empty_folder(self):
        db.set_mail_local_folder(3, "工作")
        self.assertEqual(db.empty_local_folder("工作"), 1)
        rows, _ = db.search_mails(local_folder="工作")
        self.assertEqual(rows, [])

    def test_batch_move(self):
        n = db.move_mails_to_folder([1, 2, 3], "归档")
        self.assertEqual(n, 3)
        counts = db.local_folder_counts()
        self.assertEqual(counts.get("归档"), (3, 3))

    def test_server_folder_filter_untouched(self):
        """account 维度查询不受 local_folder 影响（旧功能回归）。"""
        rows, total = db.search_mails("a1")
        self.assertEqual(len(rows), 5)
        self.assertEqual(total, 5)


class AiClientTests(unittest.TestCase):
    def test_build_request_url_and_headers(self):
        req = ai_client.build_request("https://api.deepseek.com/v1",
                                      "sk-test", "deepseek-chat",
                                      [{"role": "user", "content": "hi"}])
        self.assertTrue(req.full_url.endswith("/chat/completions"))
        self.assertEqual(req.get_header("Authorization"), "Bearer sk-test")
        import json
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["model"], "deepseek-chat")

    def test_build_request_appends_path_once(self):
        req = ai_client.build_request(
            "https://api.openai.com/v1/chat/completions", "k", "m", [])
        self.assertEqual(req.full_url,
                         "https://api.openai.com/v1/chat/completions")

    def test_build_request_requires_base_and_key(self):
        with self.assertRaises(ValueError):
            ai_client.build_request("", "k", "m", [])
        with self.assertRaises(ValueError):
            ai_client.build_request("https://x.com/v1", " ", "m", [])


class I18nTests(unittest.TestCase):
    def test_default_zh_returns_key(self):
        i18n.init("zh")
        self.assertEqual(i18n.t("立即收信"), "立即收信")

    def test_en_translation(self):
        i18n.init("en")
        try:
            self.assertEqual(i18n.t("立即收信"), "Fetch Now")
            self.assertEqual(i18n.t("不存在的键"), "不存在的键")  # 回退
        finally:
            i18n.init("zh")

    def test_en_covers_core_keys(self):
        """英文表应覆盖主要界面键（缺键会静默显示中文，这里兜底提醒）。"""
        i18n.init("en")
        try:
            for key in ("⚙ 设置", "文件夹", "收件箱", "AI 总结", "AI 写信",
                        "移动到文件夹", "附件", "打开", "另存为…", "主题",
                        "发件人", "全部", "退出", "发送"):
                self.assertNotEqual(i18n.t(key), key, f"缺英文翻译: {key}")
        finally:
            i18n.init("zh")


if __name__ == "__main__":
    unittest.main()
