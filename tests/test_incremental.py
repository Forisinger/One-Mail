# -*- coding: utf-8 -*-
"""v1.5.0：增量收信状态（folder_state）与附件名持久化 测试。"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from storage import database as db  # noqa: E402


def _mail(uid, subject="标题", body="正文", attach=None):
    return {"uid": uid, "message_id": f"<{uid}@x>", "subject": subject,
            "from_addr": "z@x.com", "from_name": "张三",
            "received_at": "2026-09-29 10:00:00", "body_text": body,
            "attachment_names": attach or []}


class FolderStateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = db._DB
        db._DB = os.path.join(self._tmp.name, "t.db")
        db.init()

    def tearDown(self):
        db._DB = self._old
        self._tmp.cleanup()

    def test_default_state(self):
        self.assertEqual(db.get_folder_state("a1", "INBOX"), (0, 0))

    def test_set_get_roundtrip(self):
        db.set_folder_state("a1", "INBOX", 12345, 42)
        self.assertEqual(db.get_folder_state("a1", "INBOX"), (12345, 42))
        db.set_folder_state("a1", "INBOX", 12345, 50)  # UPSERT 更新
        self.assertEqual(db.get_folder_state("a1", "INBOX"), (12345, 50))

    def test_folder_isolated_state(self):
        db.set_folder_state("a1", "INBOX", 1, 10)
        db.set_folder_state("a1", "Junk", 2, 20)
        self.assertEqual(db.get_folder_state("a1", "INBOX"), (1, 10))
        self.assertEqual(db.get_folder_state("a1", "Junk"), (2, 20))

    def test_delete_account_clears_state(self):
        db.set_folder_state("a1", "INBOX", 1, 10)
        db.delete_account_mails("a1")
        self.assertEqual(db.get_folder_state("a1", "INBOX"), (0, 0))


class AttachmentNamesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = db._DB
        db._DB = os.path.join(self._tmp.name, "t.db")
        db.init()

    def tearDown(self):
        db._DB = self._old
        self._tmp.cleanup()

    def test_names_persisted(self):
        db.insert_mails("a1", [_mail("u1", attach=["报告.pdf", "data.zip"])])
        row = db.list_mails()[0]
        names = json.loads(row["attachment_names"])
        self.assertEqual(names, ["报告.pdf", "data.zip"])
        self.assertEqual(row["has_attachment"], 1)

    def test_no_attachment_empty_json(self):
        db.insert_mails("a1", [_mail("u2")])
        row = db.list_mails()[0]
        self.assertEqual(json.loads(row["attachment_names"] or "[]"), [])


if __name__ == "__main__":
    unittest.main()
