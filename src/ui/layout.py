# -*- coding: utf-8 -*-
"""与 Tk 无关的布局计算（v1.11.1）：缩放适配用，可离线单测。

背景：窗口/DPI 缩放时，若分栏被压成 0 像素，整个邮件列表（连同
「来源 / 发件人 / 主题 / 时间」列头）会直接消失；列宽固定不动的旧实现
在窗口变窄后也会把最右侧的「时间」列裁掉。这里把两处计算抽成纯函数，
让修复逻辑能被单测覆盖。
"""
from __future__ import annotations

# 邮件列表四列：最小宽度 + 占可视宽度的比例
COL_MIN = {"account": 72, "from": 96, "subject": 150, "date": 94}
COL_RATIO = {"account": 0.14, "from": 0.20, "subject": 0.47, "date": 0.19}

# 分栏最小像素（防止某一栏被压成 0）
PANE_MIN_MAIL = 130      # 邮件列表（含列头）最小高度
PANE_MIN_BODY = 80       # 阅读区最小高度
PANE_MIN_LEFT = 170      # 左侧「邮件管理」栏最小宽度
PANE_MIN_RIGHT = 320     # 右侧区域最小宽度


def plan_column_widths(avail: int, col_min: dict | None = None,
                       col_ratio: dict | None = None) -> dict:
    """按可视宽度分配列宽，保证每一列都拿得到最小宽度。

    先按比例分配，再把不足最小宽的列抬到最小宽，最后的差额补给「主题」列
    （唯一可伸缩列），使总宽精确等于 avail —— 这样最右侧的「时间」列不会
    被裁掉。容器比最小宽之和还窄时按最小宽排布，由水平滚动条兜底。
    """
    col_min = COL_MIN if col_min is None else col_min
    col_ratio = COL_RATIO if col_ratio is None else col_ratio
    avail = max(int(avail), sum(col_min.values()))
    widths = {c: max(col_min[c], int(avail * r)) for c, r in col_ratio.items()}
    flex = "subject" if "subject" in widths else max(widths, key=lambda k: widths[k])
    widths[flex] = max(col_min[flex], widths[flex] + (avail - sum(widths.values())))
    return widths


def clamp_sash(pos: int, total: int, before_min: int, after_min: int) -> int:
    """把分隔条位置夹进 [before_min, total - after_min]。

    空间本身不够（total ≤ 两个最小值之和）时只做 [0, total] 的兜底夹取，
    不在极小窗口里来回抖动。返回值永远是非负的合法位置。
    """
    if total <= before_min + after_min:
        return max(0, min(int(pos), max(int(total), 0)))
    return max(0, min(max(int(pos), before_min), int(total) - after_min))


def pane_minimums(total: int, before_want: int,
                  after_want: int) -> tuple[int, int]:
    """窗口很小时按比例缩减两侧最小尺寸，保证两边都还看得见。"""
    return (min(before_want, max(60, total // 3)),
            min(after_want, max(40, total // 4)))
