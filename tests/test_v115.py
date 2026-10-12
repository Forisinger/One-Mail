# -*- coding: utf-8 -*-
"""v1.11.5：旧库升级回归测试。

复现线上崩溃：v1.3~v1.8 的 mails 表有 folder 列但缺 local_folder，
init() 必须先补列再建 idx_mails_local 索引，否则报
"no such column: local_folder" 且程序无法启动。
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from storage import database as db  # noqa: E402

_OLD_V13_SCHEMA = """
CREATE TABLE mails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    uid TEXT NOT NULL,
    folder TEXT DEFAULT 'INBOX',
    message_id TEXT,
    from_addr TEXT,
    from_name TEXT,
    subject TEXT,
    body_text TEXT,
    has_attachment INTEGER DEFAULT 0,
    received_at TEXT,
    fetched_at TEXT DEFAULT (datetime('now','localtime')),
    is_read INTEGER DEFAULT 0,
    UNIQUE(account_id, folder, uid)
);
"""


class LegacyDbUpgradeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = db._DB
        db._DB = os.path.join(self._tmp.name, "t.db")
        # 造一个 v1.3 形态的旧库（有 folder，无 local_folder/body_html/
        # attachment_names），塞两封旧邮件
        conn = sqlite3.connect(db._DB)
        conn.executescript(_OLD_V13_SCHEMA)
        conn.execute(
            "INSERT INTO mails (account_id, uid, subject, is_read) "
            "VALUES ('a1', '1', '旧邮件一', 0)")
        conn.execute(
            "INSERT INTO mails (account_id, uid, subject, is_read) "
            "VALUES ('a1', '2', '旧邮件二', 1)")
        conn.commit()
        conn.close()

    def tearDown(self):
        db._DB = self._old
        self._tmp.cleanup()

    def test_init_adds_columns_before_index(self):
        # 修复前：这里抛 sqlite3.OperationalError: no such column: local_folder
        db.init()

    def test_old_rows_survive_upgrade(self):
        db.init()
        rows = db.list_mails("a1")
        self.assertEqual(len(rows), 2)
        subjects = {r["subject"] for r in rows}
        self.assertEqual(subjects, {"旧邮件一", "旧邮件二"})

    def test_local_folder_ops_work_after_upgrade(self):
        db.init()
        rows = db.list_mails("a1")
        target = next(r for r in rows if r["subject"] == "旧邮件一")  # 未读那封
        db.set_mail_local_folder(target["id"], "工作")
        counts = db.local_folder_counts()
        self.assertEqual(counts.get("工作"), (1, 1))
        # 新邮件仍可正常入库
        new = db.insert_mails("a1", [{
            "uid": "9", "subject": "新邮件",
            "from_addr": "x@x.com", "from_name": "李四",
            "received_at": "2026-10-12 12:00:00", "body_text": "hi",
            "attachment_names": [],
        }])
        self.assertEqual(len(new), 1)


if __name__ == "__main__":
    unittest.main()
