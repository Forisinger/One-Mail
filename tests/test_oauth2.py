# -*- coding: utf-8 -*-
"""v1.10.0 新功能离线单测：OAuth2 纯函数、图片加载、账户/文件夹行为。"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core import oauth2
from core.account import Account, KNOWN_HOSTS, OAUTH_DOMAINS, oauth_provider_for
from ui import imgload


class OAuth2Pure(unittest.TestCase):
    def test_pkce_shape(self):
        v, c = oauth2.make_pkce()
        self.assertTrue(43 <= len(v) <= 128)
        expect = base64.urlsafe_b64encode(
            hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(c, expect)

    def test_auth_url_google(self):
        url = oauth2.build_auth_url(oauth2.GOOGLE, "cid", "http://localhost:1",
                                    "st", "ch")
        self.assertIn("accounts.google.com", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("access_type=offline", url)
        self.assertIn("mail.google.com", url)

    def test_auth_url_microsoft(self):
        url = oauth2.build_auth_url(oauth2.MICROSOFT, "cid", "http://localhost:1",
                                    "st", "ch")
        self.assertIn("login.microsoftonline.com", url)
        self.assertIn("offline_access", url)
        self.assertIn("IMAP.AccessAsUser.All", url)
        self.assertIn("SMTP.Send", url)

    def test_token_request_body(self):
        url, body = oauth2.build_token_request(
            oauth2.GOOGLE, "cid", "", grant_type="authorization_code",
            code="abc", redirect_uri="http://localhost:1", code_verifier="vv")
        self.assertEqual(url, oauth2.GOOGLE["token_url"])
        self.assertNotIn("client_secret", body.decode())
        self.assertIn("code_verifier=vv", body.decode())
        _url, body2 = oauth2.build_token_request(
            oauth2.GOOGLE, "cid", "sec", grant_type="refresh_token",
            refresh_token="rt")
        self.assertIn("client_secret=sec", body2.decode())

    def test_parse_token_response(self):
        d = oauth2.parse_token_response(json.dumps({
            "access_token": "at", "refresh_token": "rt", "expires_in": 3600,
        }).encode())
        self.assertEqual(d["access_token"], "at")
        self.assertGreater(d["expires_at"], time.time() + 3000)
        # 刷新不带新 refresh_token 时保留旧的
        d2 = oauth2.parse_token_response(
            json.dumps({"access_token": "at2", "expires_in": 100}).encode(),
            old=d)
        self.assertEqual(d2["refresh_token"], "rt")
        self.assertEqual(d2["access_token"], "at2")
        # 错误响应
        with self.assertRaises(oauth2.OAuth2Error):
            oauth2.parse_token_response(
                json.dumps({"error": "invalid_grant"}).encode())
        # 缺 refresh_token 且无 old
        with self.assertRaises(oauth2.OAuth2Error):
            oauth2.parse_token_response(
                json.dumps({"access_token": "x"}).encode())

    def test_token_expired(self):
        now = time.time()
        self.assertFalse(oauth2.token_expired({"expires_at": now + 1e6}, now))
        self.assertTrue(oauth2.token_expired({"expires_at": now + 60}, now))
        self.assertTrue(oauth2.token_expired({"expires_at": 0}, now))

    def test_xoauth2(self):
        raw = oauth2.xoauth2("u@x.com", "tok")
        self.assertEqual(
            raw, b"user=u@x.com\x01auth=Bearer tok\x01\x01")
        # base64 往返
        self.assertEqual(
            base64.b64decode(base64.b64encode(raw)), raw)


class OAuth2TokenStore(unittest.TestCase):
    def setUp(self):
        import core.security as sec
        self._p = mock.patch.object(sec, "_SECRETS",
                                    os.path.join(tempfile.mkdtemp(), "secrets.bin"))
        self._p.start()
        self._patch_sec()

    def tearDown(self):
        self._p.stop()

    def _patch_sec(self):
        """oauth2 模块引用的是 security 的函数对象，无需打补丁（同一模块）。"""

    def test_load_save_delete(self):
        self.assertIsNone(oauth2.load_token("a@b.com"))
        oauth2.save_token("a@b.com", {"access_token": "x", "refresh_token": "r",
                                      "expires_at": 1})
        tok = oauth2.load_token("a@b.com")
        self.assertEqual(tok["refresh_token"], "r")
        oauth2.delete_token("a@b.com")
        self.assertIsNone(oauth2.load_token("a@b.com"))

    def test_get_access_token_flow(self):
        acc = Account(id="t1", name="t", email="g@gmail.com",
                      imap_host="imap.gmail.com", auth_type="oauth2",
                      client_id="cid")
        self.assertIsNone(oauth2.load_token("g@gmail.com"))
        with self.assertRaises(oauth2.OAuth2Error):
            oauth2.get_access_token(acc)
        # 未过期：直接返回 access_token
        oauth2.save_token("g@gmail.com", {"access_token": "fresh",
                                          "refresh_token": "r",
                                          "expires_at": time.time() + 1e6,
                                          "provider": "google"})
        self.assertEqual(oauth2.get_access_token(acc), "fresh")
        # 已过期：走刷新
        oauth2.save_token("g@gmail.com", {"access_token": "stale",
                                          "refresh_token": "r",
                                          "expires_at": time.time() - 10,
                                          "provider": "google"})
        with mock.patch.object(oauth2, "refresh_token",
                               return_value={"access_token": "renewed",
                                             "refresh_token": "r2",
                                             "expires_in": 3600}):
            self.assertEqual(oauth2.get_access_token(acc), "renewed")
        tok = oauth2.load_token("g@gmail.com")
        self.assertEqual(tok["refresh_token"], "r2")


class ImageLoad(unittest.TestCase):
    PNG_1PX = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9Q"
        "DwADhgGAWjR9awAAAABJRU5ErkJggg==")

    def test_valid_image(self):
        self.assertTrue(imgload.valid_image(self.PNG_1PX))
        self.assertFalse(imgload.valid_image(b"<html>nope</html>"))
        self.assertFalse(imgload.valid_image(b""))

    def test_collect_images(self):
        imgs = imgload.collect_images(
            '<img src="cid:img001@example.com"><IMG SRC="https://x/y.png">')
        self.assertEqual(len(imgs), 2)
        self.assertTrue(imgs[0].cid)
        self.assertEqual(imgload.cid_from_src("cid:img001@example.com"),
                         "img001@example.com")

    def test_download_rejects_non_http(self):
        with self.assertRaises(ValueError):
            imgload.download("ftp://x/y.png")
        with self.assertRaises(ValueError):
            imgload.download("file:///C:/x.png")

    def test_data_uri(self):
        data = imgload.data_b64_from_src(
            "data:image/png;base64," + base64.b64encode(self.PNG_1PX).decode())
        self.assertTrue(data and imgload.valid_image(data))
        self.assertIsNone(imgload.data_b64_from_src("data:text/html;base64,QQ=="))

    def test_cid_map(self):
        from email.message import EmailMessage
        m = EmailMessage()
        m["Subject"] = "x"
        m.set_content("body")
        m.add_attachment(self.PNG_1PX, maintype="image", subtype="png",
                         cid="<img001@example.com>")
        cmap = imgload.cid_map_from_raw(m.as_bytes())
        self.assertIn("img001@example.com", cmap)
        self.assertTrue(imgload.valid_image(cmap["img001@example.com"]))

    def test_htmltext_img_placeholder(self):
        import tkinter as tk
        from ui.htmltext import render_html
        try:
            root = tk.Tk()
            root.withdraw()
        except Exception:
            self.skipTest("no display")
        try:
            t = tk.Text(root)
            html = '<p>前</p><img src="cid:a@x"><img src="https://h/i.png" alt="LOGO"/>'
            images = render_html(t, html, ("Microsoft YaHei UI", 10),
                                 {"GRAY": "#888", "ACCENT": "#06c"})
            self.assertEqual(len(images), 2)
            content = t.get("1.0", "end")
            self.assertIn("前", content)
            self.assertIn("［图片］", content)
            self.assertIn("LOGO", content)
        finally:
            root.destroy()


class AccountPresets(unittest.TestCase):
    def test_provider_guess(self):
        self.assertEqual(oauth_provider_for("x@Gmail.com"), "google")
        self.assertEqual(oauth_provider_for("x@googlemail.com"), "google")
        self.assertEqual(oauth_provider_for("x@outlook.com"), "microsoft")
        self.assertEqual(oauth_provider_for("x@hotmail.co.uk"), "microsoft")
        self.assertIsNone(oauth_provider_for("x@qq.com"))

    def test_known_hosts(self):
        self.assertEqual(KNOWN_HOSTS["gmail.com"], ("imap.gmail.com", 993))
        self.assertEqual(KNOWN_HOSTS["outlook.com"],
                         ("outlook.office365.com", 993))
        self.assertEqual(OAUTH_DOMAINS["outlook.com"],
                         ("microsoft", "smtp.office365.com", 587))
        self.assertEqual(OAUTH_DOMAINS["gmail.com"],
                         ("google", "smtp.gmail.com", 465))

    def test_account_fields_default(self):
        a = Account(id="a", name="n", email="e@x.com", imap_host="h")
        self.assertEqual(a.auth_type, "password")
        self.assertEqual(a.client_id, "")


if __name__ == "__main__":
    unittest.main()
