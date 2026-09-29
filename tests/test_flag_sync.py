# -*- coding: utf-8 -*-
"""v1.7.0：FlagSync 已读同步核心逻辑测试（假 connector，不起真网络/线程）。"""
import os
import sys
import threading
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.flag_sync import FlagSync, CHUNK_SIZE  # noqa: E402


def _account(acc_id="a1"):
    return SimpleNamespace(id=acc_id, email=f"{acc_id}@x.com",
                           imap_host="imap.x.com", imap_port=993, ssl=True)


class _Harness:
    """收集 connector 调用的假环境。"""

    def __init__(self, accounts=None, enabled=True, fail_first=0):
        self.calls = []          # [(account_id, folder, uids, seen)]
        self.accounts = accounts or {"a1": _account()}
        self._enabled = enabled
        self.fail_first = fail_first   # connector 前 N 次调用抛异常
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
        # start_thread=False：不起真线程，消除 qsize/get_nowait 竞态
        return FlagSync(self.get_credentials, connector=self.connector,
                        enabled=self.enabled, log=lambda m: None,
                        start_thread=False)

    def account_of(self, i):
        return self.calls[i][0]


def _stop(fs):
    fs.stop()


class FlagSyncTests(unittest.TestCase):
    def tearDown(self):
        pass  # 各测试内自建 FlagSync，daemon 线程由 stop() 结束

    def _process(self, h, jobs):
        fs = h.make()
        try:
            fs._process_batch([(a, f, u, s, 0) for a, f, u, s in jobs])
        finally:
            _stop(fs)
        return h

    def test_dedup_same_key(self):
        """同 key 重复提交只处理一次。"""
        h = _Harness()
        fs = h.make()
        try:
            fs.submit("a1", "INBOX", "12", seen=True)
            fs.submit("a1", "INBOX", "12", seen=True)
            self.assertEqual(fs._queue.qsize(), 1)
        finally:
            _stop(fs)

    def test_group_by_account_folder(self):
        """跨账户/文件夹的任务按组聚合，组内 UID 一次 connector。"""
        h = _Harness(accounts={"a1": _account("a1"), "a2": _account("a2")})
        self._process(h, [
            ("a1", "INBOX", "3", True),
            ("a1", "INBOX", "1", True),
            ("a2", "INBOX", "5", True),
            ("a1", "已发送", "2", True),
        ])
        self.assertEqual(len(h.calls), 3)
        by = {(c[0], c[1]): c[2] for c in h.calls}
        self.assertEqual(by[("a1", "INBOX")], ["1", "3"])
        self.assertEqual(by[("a2", "INBOX")], ["5"])
        self.assertEqual(by[("a1", "已发送")], ["2"])

    def test_uid_numeric_sort(self):
        """UID 按数值排序而非字典序：["10","2"] -> ["2","10"]。"""
        h = self._process(_Harness(), [("a1", "INBOX", "10", True),
                                       ("a1", "INBOX", "2", True)])
        self.assertEqual(h.calls[0][2], ["2", "10"])

    def test_chunk_size(self):
        """超过 CHUNK_SIZE 的组切块发送（120 个 -> 50/50/20）。"""
        uids = [str(i) for i in range(1, 121)]
        h = self._process(_Harness(), [("a1", "INBOX", u, True) for u in uids])
        self.assertEqual(len(h.calls), 3)
        self.assertEqual([len(c[2]) for c in h.calls], [50, 50, 20])
        self.assertEqual(h.calls[0][2][0], "1")
        self.assertEqual(h.calls[2][2][-1], "120")

    def test_inline_retry_then_success(self):
        """首次失败组内内联重试一次后成功；不回队（保序）。"""
        h = _Harness(fail_first=1)
        fs = h.make()
        try:
            fs._process_batch([("a1", "INBOX", "7", True, 0)])
            self.assertEqual(len(h.calls), 2)          # 失败 + 内联重试成功
            self.assertEqual(fs._queue.qsize(), 0)     # 绝不回队
            self.assertNotIn(("a1", "INBOX", "7", True), fs._pending)
        finally:
            _stop(fs)

    def test_drop_after_inline_retry_fails(self):
        """内联重试仍失败：丢弃并释放去重键。"""
        h = _Harness(fail_first=2)
        fs = h.make()
        try:
            fs._process_batch([("a1", "INBOX", "7", True, 0)])
            self.assertEqual(len(h.calls), 2)
            self.assertEqual(fs._queue.qsize(), 0)     # 丢弃
            self.assertNotIn(("a1", "INBOX", "7", True), fs._pending)
        finally:
            _stop(fs)

    def test_disabled_no_call(self):
        """总开关关闭：任务直接丢弃，不碰网络。"""
        h = _Harness(enabled=False)
        self._process(h, [("a1", "INBOX", "1", True)])
        self.assertEqual(h.calls, [])

    def test_missing_account_dropped(self):
        """账户已删/无授权码：安全丢弃不崩。"""
        h = _Harness(accounts={})
        self._process(h, [("ghost", "INBOX", "1", True)])
        self.assertEqual(h.calls, [])

    def test_unseen_uses_minus_flags_path(self):
        """seen=False 任务正常分组处理（-FLAGS 由 mark_seen 层实现）。"""
        h = self._process(_Harness(), [("a1", "INBOX", "4", False)])
        self.assertEqual(h.calls[0][3], False)

    def test_success_clears_pending(self):
        """成功后去重键必须释放：同邮件可再次投递（如再标未读再标已读）。"""
        h = _Harness()
        fs = h.make()
        try:
            fs._process_batch([("a1", "INBOX", "9", True, 0)])
            self.assertNotIn(("a1", "INBOX", "9", True), fs._pending)
            fs._process_batch([("a1", "INBOX", "9", True, 0)])
            self.assertEqual(len(h.calls), 2)
        finally:
            fs.stop()

    def test_invalid_uid_filtered(self):
        """非数字 UID 被剔除不崩溃，合法 UID 照常处理，键全部释放。"""
        h = _Harness()
        fs = h.make()
        try:
            fs._process_batch([("a1", "INBOX", "bad", True, 0),
                               ("a1", "INBOX", "5", True, 0)])
            self.assertEqual(len(h.calls), 1)
            self.assertEqual(h.calls[0][2], ["5"])
            self.assertEqual(fs._pending, set())
        finally:
            fs.stop()

    def test_partial_chunk_retry(self):
        """多块时只有失败块内联重试，成功块不重发。"""
        uids = [str(i) for i in range(1, 61)]   # 60 个 -> 50 + 10 两块
        h = _Harness(fail_first=1)              # 第一块首次失败
        fs = h.make()
        try:
            fs._process_batch([("a1", "INBOX", u, True, 0) for u in uids])
            self.assertEqual(len(h.calls), 3)          # 失败 + 重试 + 第二块
            self.assertEqual([len(c[2]) for c in h.calls], [50, 50, 10])
            self.assertEqual(fs._queue.qsize(), 0)     # 无回队任务
            self.assertEqual(fs._pending, set())       # 全部键已释放
        finally:
            fs.stop()

    def test_submit_folder_none_normalized(self):
        """folder=None 归一化为 INBOX。"""
        h = _Harness()
        fs = h.make()
        try:
            fs.submit("a1", None, "3", seen=True)
            self.assertIn(("a1", "INBOX", "3", True), fs._pending)
        finally:
            fs.stop()


class ChunkSizeTests(unittest.TestCase):
    def test_chunk_is_positive(self):
        self.assertGreaterEqual(CHUNK_SIZE, 1)


class MarkSeenImaplibTests(unittest.TestCase):
    """mark_seen 的 imaplib 交互 mock 测试（复查盲区补齐）。"""

    def _mock_conn(self):
        from unittest.mock import MagicMock
        conn = MagicMock()
        conn.login.return_value = ("OK", [b"Logged in"])
        conn.select.return_value = ("OK", [b"3"])
        conn.uid.return_value = ("OK", [None])
        conn.logout.return_value = ("BYE", [b""])
        return conn

    def test_store_calls_and_seq_set(self):
        """验证：非 readonly SELECT、.SILENT 标志、UID 数值排序 seq-set、logout。"""
        import imaplib as real_imaplib
        from unittest.mock import patch
        from core import mail_client as mc

        conn = self._mock_conn()
        with patch.object(real_imaplib, "IMAP4_SSL", return_value=conn):
            mc.MailClient.mark_seen(_account(), "pwd", "INBOX",
                                    ["10", "2"], seen=True)
        conn.select.assert_called_once()
        args = conn.select.call_args
        self.assertFalse(args.kwargs.get("readonly", True)
                         if args.kwargs else args[1].get("readonly", True))
        conn.uid.assert_called_once_with(
            "store", "2,10", "(+FLAGS.SILENT (\\Seen))")
        conn.logout.assert_called_once()

    def test_store_unseen_uses_minus_silent(self):
        import imaplib as real_imaplib
        from unittest.mock import patch
        from core import mail_client as mc

        conn = self._mock_conn()
        with patch.object(real_imaplib, "IMAP4_SSL", return_value=conn):
            mc.MailClient.mark_seen(_account(), "pwd", "已发送",
                                    ["5"], seen=False)
        conn.uid.assert_called_once_with(
            "store", "5", "(-FLAGS.SILENT (\\Seen))")

    def test_select_no_raises(self):
        """SELECT 返回 NO（文件夹不存在）必须抛错，而不是莫名状态机错误。"""
        import imaplib as real_imaplib
        from unittest.mock import patch
        from core import mail_client as mc

        conn = self._mock_conn()
        conn.select.return_value = ("NO", [b"Mailbox doesn't exist"])
        with patch.object(real_imaplib, "IMAP4_SSL", return_value=conn):
            with self.assertRaises(real_imaplib.IMAP4.error):
                mc.MailClient.mark_seen(_account(), "pwd", "不存在",
                                        ["5"], seen=True)
        conn.uid.assert_not_called()   # 不应继续 STORE

    def test_store_failure_raises(self):
        """STORE 返回 NO 抛 IMAP4.error（走 flag_sync 重试路径）。"""
        import imaplib as real_imaplib
        from unittest.mock import patch
        from core import mail_client as mc

        conn = self._mock_conn()
        conn.uid.return_value = ("NO", [b"failed"])
        with patch.object(real_imaplib, "IMAP4_SSL", return_value=conn):
            with self.assertRaises(real_imaplib.IMAP4.error):
                mc.MailClient.mark_seen(_account(), "pwd", "INBOX",
                                        ["5"], seen=True)

    def test_bad_uids_skipped_entirely(self):
        """全部 UID 非法时不建连接直接返回。"""
        from unittest.mock import patch
        import imaplib as real_imaplib
        from core import mail_client as mc

        with patch.object(real_imaplib, "IMAP4_SSL") as factory:
            mc.MailClient.mark_seen(_account(), "pwd", "INBOX",
                                    ["bad"], seen=True)
        factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
