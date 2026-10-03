# -*- coding: utf-8 -*-
"""源码级静态检查（不依赖 tkinter / 不启动 UI）。

这些检查针对"能通过编译但运行时才炸"的真实缺陷类型：
1. 本地导入路径必须真实存在（例如把 src/autostart.py 误写成 core.autostart）
2. `except ... as e` 的 e 不能被延迟执行的 lambda 捕获——except 块结束后
   Python 会删除 e，回调里只会抛 NameError，而 UI 那边往往用 try/except
   兜底，于是失败信息被静默吞掉，用户什么也看不到
"""
import ast
import os
import re
import unittest

_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))

# src 内的本地顶层模块/包（其余为 stdlib 或第三方，一律跳过）
_LOCAL = ("core", "storage", "ui", "autostart", "notify", "single_instance")

# 调色板唯一定义处：其余地方出现颜色字面量都视为"没跟随主题"
_COLOR_DEFINITION_FILES = {"theme.py"}
_COLOR_LITERAL_RE = re.compile(
    r"^#[0-9a-fA-F]{3,8}$|^(white|black|gray|grey|lightgray|lightgrey|darkgray)$")


def _iter_sources():
    for dirpath, _dirs, files in os.walk(_SRC):
        for fn in sorted(files):
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def _is_module(path_no_ext: str) -> bool:
    return (os.path.isfile(path_no_ext + ".py")
            or os.path.isfile(os.path.join(path_no_ext, "__init__.py")))


def _is_package(path: str) -> bool:
    return os.path.isfile(os.path.join(path, "__init__.py"))


def _local_targets(tree: ast.AST, pkg_dir: str) -> list[str]:
    """收集所有"应当存在于磁盘"的本地导入目标路径。"""
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in _LOCAL:
                    out.append(os.path.join(_SRC, *a.name.split(".")))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg_dir
                for _ in range(node.level - 1):
                    base = os.path.dirname(base)
                if node.module:
                    out.append(os.path.join(base, *node.module.split(".")))
                else:
                    for a in node.names:
                        if not a.name.startswith("_"):
                            out.append(os.path.join(base, a.name))
            elif (node.module or "").split(".")[0] in _LOCAL:
                base = os.path.join(_SRC, *node.module.split("."))
                out.append(base)
                # 从"包"里导入的名字必须是该包的子模块（本仓库约定：
                # from core import security / from . import i18n）；
                # `from xxx.module import Symbol` 时 base 是文件，不校验名字
                if _is_package(base):
                    for a in node.names:
                        if not a.name.startswith("_"):
                            out.append(os.path.join(base, a.name))
    return out


class LocalImportTests(unittest.TestCase):
    def test_local_imports_resolve(self):
        problems: list[str] = []
        for path in _iter_sources():
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for target in _local_targets(tree, os.path.dirname(path)):
                if not _is_module(target):
                    problems.append(
                        f"{os.path.relpath(path, _SRC)} → "
                        f"{os.path.relpath(target, _SRC)}")
        self.assertEqual(problems, [], "本地导入路径不存在: " + "; ".join(problems))


class ExceptVariableClosureTests(unittest.TestCase):
    """`except ... as e` 的 e 不得被嵌套 lambda 捕获。

    该模式在编译期无异常、pyflakes 会报 "undefined name"，但更麻烦的是
    它常常被静默吞掉（回调里再套 try/except），表现为"操作失败但界面没
    任何提示"。这里做全仓扫描，防止回归。
    """

    def test_no_lambda_captures_except_variable(self):
        found: list[str] = []
        for path in _iter_sources():
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Try):
                    continue
                for handler in node.handlers:
                    if not handler.name:
                        continue
                    for inner in ast.walk(handler):
                        if not isinstance(inner, ast.Lambda):
                            continue
                        if any(isinstance(x, ast.Name) and x.id == handler.name
                               for x in ast.walk(inner)):
                            found.append(f"{os.path.relpath(path, _SRC)}:"
                                         f"{handler.lineno} → {handler.name!r}")
        self.assertEqual(found, [], "except 变量被 lambda 捕获: " + "; ".join(found))


class HardcodedColorTests(unittest.TestCase):
    """除了调色板定义处，src 内不得出现颜色字面量。

    这是"深色主题下仍有浅色控件"这类 bug 的回归防线：任何硬编码的
    `bg="#ffffff"` / `foreground="#888"` 都不会跟随主题切换。
    允许 `.get("KEY", "#fff")` 形式的兜底默认值（只有当调色板缺键时才用）。
    """

    def test_no_hardcoded_colors_outside_palette(self):
        get_fallbacks: set[int] = set()
        problems: list[str] = []
        trees = {}
        for path in _iter_sources():
            with open(path, encoding="utf-8") as f:
                trees[path] = ast.parse(f.read())
        # 先收集所有 .get(key, <常量>) 的兜底参数节点
        for tree in trees.values():
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "get"
                        and len(node.args) >= 2):
                    get_fallbacks.add(id(node.args[1]))
        for path, tree in trees.items():
            if os.path.basename(path) in _COLOR_DEFINITION_FILES:
                continue
            rel = os.path.relpath(path, _SRC)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and _COLOR_LITERAL_RE.match(node.value)
                        and id(node) not in get_fallbacks):
                    problems.append(f"{rel}:{node.lineno} {node.value!r}")
        self.assertEqual(problems, [],
                         "硬编码颜色（应改用主题调色板）: " + "; ".join(problems))


class MenuPopupDestroyTests(unittest.TestCase):
    """右键菜单不得在 tk_popup 返回后立即 destroy（v1.11.3 回归防线）。

    Windows 上菜单项命令在 tk_popup 返回之后才异步 invoke；紧跟的
    destroy() 会把尚未分发的 command 连同菜单一起销毁，表现为"点了
    菜单项没有任何反应"（右键删除邮件 bug 的根因）。弹菜单必须走
    MainWindow._popup_menu（延迟销毁），其他地方只允许出现一次
    tk_popup 调用（即 _popup_menu 内部那一处）。
    """

    def test_tk_popup_only_via_popup_menu_helper(self):
        found: list[str] = []
        for path in _iter_sources():
            with open(path, encoding="utf-8") as f:
                src = f.read()
            if "tk_popup" not in src:
                continue
            rel = os.path.relpath(path, _SRC)
            if rel.replace("\\", "/") == "ui/main_window.py":
                # 主窗口允许且仅允许 _popup_menu 一处
                calls = src.count(".tk_popup(")
                if calls != 1:
                    found.append(f"{rel}: tk_popup 出现 {calls} 次（应为 1）")
                if re.search(r"\.tk_popup\(.*\)\s*\n\s*\S*\.?grab_release\(\)"
                             r"\s*\n\s*\S*\.?destroy\(\)", src):
                    found.append(f"{rel}: tk_popup 后紧跟 destroy（会吞命令）")
            else:
                found.append(f"{rel}: 不应直接调用 tk_popup")
        self.assertEqual(found, [], "右键菜单销毁时序隐患: " + "; ".join(found))


if __name__ == "__main__":
    unittest.main()
