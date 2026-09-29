# -*- coding: utf-8 -*-
"""v1.4.0 稳定性加固回归测试。"""
import os
import sys
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from storage import database as db  # noqa: E402
from storage import config as config_store  # noqa: E402
from core.account import Account  # noqa: E402
from core.parser import _HTML2Text  # noqa: E402
from core import smtp_client  # noqa: E402


def _mail(uid, subject="标题", body="正文", from_addr="z@x.com", from_name="张三"):
    return {"uid": uid, "message_id": f"<{uid}@x>", "subject": subject,
            "from_addr": from_addr, "from_name": from_name,
            "received_at": "2026-09-29 10:00:00", "body_text": body,
            "attachment_names": []}


class LikeEscapeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = db._DB
        db._DB = os.path.join(self._tmp.name, "t.db")
        db.init()
        db.insert_mails("a1", [_mail("u1", subject="折扣100%"),
                               _mail("u2", subject="a_b 命名"),
                               _mail("u3", subject="普通")])

    def tearDown(self):
        db._DB = self._old
        self._tmp.cleanup()

    def test_percent_literal(self):
        rows, _ = db.search_mails(keyword="100%")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["subject"], "折扣100%")

    def test_underscore_literal(self):
        rows, _ = db.search_mails(keyword="a_b")
        self.assertEqual(len(rows), 1)

    def test_delete_mail(self):
        rows, total = db.search_mails()
        self.assertEqual(total, 3)
        db.delete_mail(rows[0]["id"])
        _, total = db.search_mails()
        self.assertEqual(total, 2)


class ParserUnclosedSkipTests(unittest.TestCase):
    def _html(self, s):
        p = _HTML2Text()
        p.feed(s)
        return p.text()

    def test_unclosed_script_keeps_body(self):
        html = "<html><script>var x = 1; <body><p>正文在这里</p></body></html>"
        self.assertIn("正文在这里", self._html(html))

    def test_unclosed_style_keeps_body(self):
        html = "<style>p { color: red; <div>有效正文</div>"
        self.assertIn("有效正文", self._html(html))

    def test_wellformed_script_still_hidden(self):
        html = "<script>var x=1;</script><p>可见</p>"
        out = self._html(html)
        self.assertIn("可见", out)
        self.assertNotIn("var x", out)

    def test_nested_head_title(self):
        html = "<head><title>标题</title></head><p>内容</p>"
        out = self._html(html)
        self.assertIn("内容", out)
        self.assertNotIn("标题", out)


class GuessHostBoundaryTests(unittest.TestCase):
    def test_exact_and_subdomain(self):
        self.assertEqual(Account.guess_host("a@qq.com")[0], "imap.qq.com")
        self.assertEqual(Account.guess_host("a@mail.qq.com")[0], "imap.qq.com")

    def test_lookalike_domain_not_matched(self):
        # myqq.com / x163.com 不能命中 qq.com / 163.com（凭据误发风险）
        self.assertEqual(Account.guess_host("a@myqq.com")[0], "imap.myqq.com")
        self.assertEqual(Account.guess_host("a@x163.com")[0], "imap.x163.com")


class SmtpHeaderTests(unittest.TestCase):
    def test_date_and_message_id_present(self):
        acc = Account(id="x", name="n", email="u@163.com",
                      imap_host="imap.163.com")
        msg = smtp_client.build_mime(acc, ["to@x.com"], "hi", "body")
        self.assertTrue(msg["Date"])
        self.assertTrue(msg["Message-ID"])
        self.assertIn("163.com", msg["Message-ID"])


class ConfigAtomicTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = config_store._CONFIG
        config_store._CONFIG = os.path.join(self._tmp.name, "config.json")

    def tearDown(self):
        config_store._CONFIG = self._old
        self._tmp.cleanup()

    def test_save_load_roundtrip(self):
        data = {"accounts": [{"id": "a1", "name": "n"}],
                "settings": {"autostart": True}}
        config_store.save(data)
        loaded = config_store.load()
        self.assertEqual(loaded["accounts"][0]["id"], "a1")

    def test_corrupt_config_backed_up_not_overwritten(self):
        with open(config_store._CONFIG, "w", encoding="utf-8") as f:
            f.write('{"accounts": [ broken')
        loaded = config_store.load()  # 损坏 -> 备份为 .corrupt -> 回默认
        self.assertEqual(loaded["accounts"], [])
        self.assertTrue(os.path.exists(config_store._CONFIG + ".corrupt"))
        # 备份内容仍可找回原始数据
        with open(config_store._CONFIG + ".corrupt", encoding="utf-8") as f:
            self.assertIn("broken", f.read())

    def test_no_temp_file_left_behind(self):
        config_store.save({"accounts": [], "settings": {}})
        self.assertFalse(os.path.exists(config_store._CONFIG + ".tmp"))


class MigrationIdempotencyTests(unittest.TestCase):
    def test_half_migrated_state_recovers(self):
        """升级中断留下的 mails_new 不应让下次启动崩溃。"""
        self._tmp = tempfile.TemporaryDirectory()
        db._DB = os.path.join(self._tmp.name, "old.db")
        conn = sqlite3.connect(db._DB)
        conn.executescript("""
            CREATE TABLE mails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL,
                uid TEXT NOT NULL,
                message_id TEXT, from_addr TEXT, from_name TEXT,
                subject TEXT, body_text TEXT,
                has_attachment INTEGER DEFAULT 0, received_at TEXT,
                fetched_at TEXT, is_read INTEGER DEFAULT 0,
                UNIQUE(account_id, uid)
            );
            CREATE TABLE mails_new (id INTEGER PRIMARY KEY);
            INSERT INTO mails (account_id, uid, subject, is_read)
            VALUES ('a1', 'u1', '遗留邮件', 0);
        """)
        conn.commit()
        conn.close()

        db.init()  # 迁移应清掉残留 mails_new 并成功完成
        rows = db.list_mails()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["folder"], "INBOX")
        self.assertEqual(rows[0]["subject"], "遗留邮件")
        self._tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
