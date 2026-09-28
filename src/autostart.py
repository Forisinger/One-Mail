# -*- coding: utf-8 -*-
"""开机自启：HKCU 注册表 Run 项，用户级，无需管理员权限。"""
from __future__ import annotations

import os
import sys

if os.name == "nt":
    import winreg

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "OneMail"


def _exe_command() -> str:
    """返回自启命令。打包后为 exe 自身路径；脚本运行为 pythonw + main.py。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "src", "main.py")
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    interpreter = pythonw if os.path.exists(pythonw) else sys.executable
    return f'"{interpreter}" "{main_py}" --minimized'


def enabled() -> bool:
    if os.name != "nt":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_enabled(on: bool) -> bool:
    """设置/取消开机自启。返回操作是否成功。"""
    if os.name != "nt":
        return False
    try:
        if on:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _exe_command())
        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                                    winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, _VALUE_NAME)
            except FileNotFoundError:
                pass
        return True
    except OSError:
        return False
