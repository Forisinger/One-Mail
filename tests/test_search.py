# -*- coding: utf-8 -*-
"""v1.3.0：数据库迁移 / folder 去重 / search_mails 组合搜索 测试。"""
import os
import sys
import tempfile
import unittest
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from storage import database as db  # noqa: E402
from core.account import Account  # noqa: E402


def _mail(uid, subject="标题", body="正文", from_name="张三",
          from_addr="z@x.com", attach=False, read=False):
    return {
        "uid": uid, "message_id": f"<{uid}@x>", "subject": subject,
        "from_addr": from_addr, "from_name": from_name,
        "received_at": "2026-09-29 10:00:00", "body_text": body,
        "attachment_names": ["a.pdf"] if attach else [],
        "_read": read,
    }


class SearchFolderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = db._DB
        db._DB = os.path.join(self._tmp.name, "t.db")
        db.init()

    def tearDown(self):
        db._DB = self._old_db
        self._tmp.cleanup()

    def _insert(self, mails, folder="INBOX", account="a1"):
        new = db.insert_mails(account, mails, folder=folder)
        for m, n in zip(mails, mails):
            pass
        return new

    def test_folder_isolation(self):
        """同账户同 UID 在不同文件夹可共存。"""
        m = _mail("u1")
        self._insert([m], folder="INBOX")
        self._insert([m], folder="Junk")
        rows = db.list_mails()
        self.assertEqual(len(rows), 2)
        folders = {r["folder"] for r in rows}
        self.assertEqual(folders, {"INBOX", "Junk"})

    def test_dedup_same_folder(self):
        m = _mail("u1")
        first = self._insert([dict(m)], folder="INBOX")
        second = self._insert([dict(m)], folder="INBOX")
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)

    def test_search_by_body(self):
        self._insert([_mail("u1", subject="会议通知", body="明天下午三点开会"),
                      _mail("u2", subject="账单", body="您的发票已开具")])
        rows, total = db.search_mails(keyword="发票")
        self.assertEqual(total, 2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["subject"], "账单")

    def test_search_by_subject_and_sender(self):
        self._insert([_mail("u1", subject="周报", from_name="李四"),
                      _mail("u2", subject="周报", from_name="王五",
                            from_addr="w@x.com")])
        rows, _ = db.search_mails(keyword="李四")
        self.assertEqual(len(rows), 1)
        rows, _ = db.search_mails(keyword="w@x.com")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["from_name"], "王五")

    def test_filter_unread_and_attach(self):
        self._insert([_mail("u1", attach=True, read=False),
                      _mail("u2", attach=False, read=False),
                      _mail("u3", attach=True, read=True)])
        # u3 标记已读（insert 不带已读状态，与真实收信流程一致）
        rows = db.list_mails()
        for r in rows:
            if r["uid"] == "u3":
                db.mark_read(r["id"])
        rows, total = db.search_mails(unread_only=True)
        self.assertEqual(total, 3)
        self.assertEqual(len(rows), 2)
        rows, _ = db.search_mails(has_attach=True)
        self.assertEqual(len(rows), 2)
        rows, _ = db.search_mails(unread_only=True, has_attach=True)
        self.assertEqual(len(rows), 1)

    def test_account_filter_combined(self):
        db.insert_mails("a1", [_mail("u1", body="hello")], folder="INBOX")
        db.insert_mails("a2", [_mail("u2", body="hello")], folder="INBOX")
        rows, total = db.search_mails(account_id="a1", keyword="hello")
        self.assertEqual(total, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["account_id"], "a1")

    def test_migration_from_old_schema(self):
        """旧 schema（无 folder 列、唯一键 account_id+uid）数据无损升级。"""
        db._DB = os.path.join(self._tmp.name, "old.db")
        conn = sqlite3.connect(db._DB)
        conn.executescript("""
            CREATE TABLE mails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL,
                uid TEXT NOT NULL,
                message_id TEXT,
                from_addr TEXT,
                from_name TEXT,
                subject TEXT,
                body_text TEXT,
                has_attachment INTEGER DEFAULT 0,
                received_at TEXT,
                fetched_at TEXT DEFAULT (datetime('now','localtime')),
                is_read INTEGER DEFAULT 0,
                UNIQUE(account_id, uid)
            );
        """)
        conn.execute(
            "INSERT INTO mails (account_id, uid, subject, body_text, is_read)"
            " VALUES ('a1', 'old1', '旧邮件', '迁移前数据', 0)")
        conn.commit()
        conn.close()

        db.init()  # 触发迁移
        rows = db.list_mails()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["folder"], "INBOX")
        self.assertEqual(rows[0]["subject"], "旧邮件")
        # 迁移后仍可正常写入/去重
        new = db.insert_mails("a1", [_mail("new1")], folder="INBOX")
        self.assertEqual(len(new), 1)

    def test_account_folder_default(self):
        acc = Account(id="x", name="n", email="a@b.com", imap_host="imap.b.com")
        self.assertEqual(acc.folder, "INBOX")
        acc2 = Account.from_dict({**acc.to_dict(), "folder": "Junk"})
        self.assertEqual(acc2.folder, "Junk")
        # 旧配置无 folder 字段也能加载
        acc3 = Account.from_dict({"id": "y", "name": "n", "email": "a@b.com",
                                  "imap_host": "imap.b.com"})
        self.assertEqual(acc3.folder, "INBOX")

    def test_mutf7_decode(self):
        from core.mail_client import _decode_mutf7
        self.assertEqual(_decode_mutf7("INBOX"), "INBOX")
        # 常见中文文件夹（163/QQ 返回的 mUTF-7 原始名）
        self.assertEqual(_decode_mutf7("&XfJT0ZAB-"), "已发送")
        self.assertEqual(_decode_mutf7("&g0l6P3ux-"), "草稿箱")
        self.assertEqual(_decode_mutf7("&V4NXPpCuTvY-"), "垃圾邮件")
        self.assertEqual(_decode_mutf7("Sent&-1"), "Sent&1")  # "&-" 表示字面 &

    def test_mutf7_roundtrip(self):
        from core.mail_client import _decode_mutf7, _encode_mutf7
        for name in ("已发送", "草稿箱", "垃圾邮件", "Sent", "我的&笔记",
                     "INBOX/子文件夹", "工作 邮件"):
            self.assertEqual(_decode_mutf7(_encode_mutf7(name)), name)
        # 已发送 的编码就是服务器返回的原始形式
        self.assertEqual(_encode_mutf7("已发送"), "&XfJT0ZAB-")

    def test_folder_wire(self):
        from core.mail_client import MailClient
        acc = Account(id="x", name="n", email="a@163.com",
                      imap_host="imap.163.com")
        acc.folder = "INBOX"
        self.assertEqual(MailClient(acc, "", None, None)._folder_wire(),
                         '"INBOX"')
        acc.folder = "已发送"
        self.assertEqual(MailClient(acc, "", None, None)._folder_wire(),
                         '"&XfJT0ZAB-"')
        acc.folder = "Sent Messages"
        self.assertEqual(MailClient(acc, "", None, None)._folder_wire(),
                         '"Sent Messages"')
        # 纯 ASCII 的 & 必须转义为 &-（mUTF-7 规范），不做原始名直通猜测
        acc.folder = "A&B"
        self.assertEqual(MailClient(acc, "", None, None)._folder_wire(),
                         '"A&-B"')
        acc.folder = "Tom&Jerry-x"
        self.assertEqual(MailClient(acc, "", None, None)._folder_wire(),
                         '"Tom&-Jerry-x"')


if __name__ == "__main__":
    unittest.main()
