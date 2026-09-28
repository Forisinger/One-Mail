# -*- coding: utf-8 -*-
"""密码安全存储：Windows DPAPI（ctypes 实现，零第三方依赖）。

加密结果绑定当前 Windows 用户，密文落盘 %APPDATA%/OneMail/secrets.bin。
"""
from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes

if os.name != "nt":  # 非 Windows 环境（开发/测试用）退化为明文混淆
    _DPAPI = False
else:
    _DPAPI = True
    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _dpapi_protect(plain: bytes) -> bytes:
    in_blob, out_blob = _blob(plain), _DATA_BLOB()
    if not _crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        _kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(cipher: bytes) -> bytes:
    in_blob, out_blob = _blob(cipher), _DATA_BLOB()
    if not _crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise OSError("CryptUnprotectData failed（可能换用户/换机器）")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        _kernel32.LocalFree(out_blob.pbData)


def data_dir() -> str:
    base = os.environ.get("APPDATA") if os.name == "nt" else os.path.expanduser("~")
    path = os.path.join(base or ".", "OneMail")
    os.makedirs(path, exist_ok=True)
    return path


_SECRETS = os.path.join(data_dir(), "secrets.bin")


def save_password(account_id: str, password: str) -> None:
    """保存（加密）一个账户的密码。"""
    store: dict = {}
    if os.path.exists(_SECRETS):
        try:
            store = json.loads(_read_secrets())
        except Exception:
            store = {}
    if _DPAPI:
        store[account_id] = _dpapi_protect(password.encode("utf-8")).hex()
    else:
        store[account_id] = password  # 非 Windows 测试环境明文
    with open(_SECRETS, "w", encoding="utf-8") as f:
        json.dump(store, f)


def load_password(account_id: str) -> str:
    if not os.path.exists(_SECRETS):
        return ""
    try:
        store = json.loads(_read_secrets())
        val = store.get(account_id, "")
        if not val:
            return ""
        if _DPAPI:
            return _dpapi_unprotect(bytes.fromhex(val)).decode("utf-8")
        return val
    except Exception:
        return ""


def delete_password(account_id: str) -> None:
    if not os.path.exists(_SECRETS):
        return
    try:
        store = json.loads(_read_secrets())
        store.pop(account_id, None)
        with open(_SECRETS, "w", encoding="utf-8") as f:
            json.dump(store, f)
    except Exception:
        pass


def _read_secrets() -> str:
    with open(_SECRETS, "r", encoding="utf-8") as f:
        return f.read()
