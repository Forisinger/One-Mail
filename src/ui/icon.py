# -*- coding: utf-8 -*-
"""托盘图标绘制：基础信封图标 + 未读计数角标。

用 Pillow 动态绘制，无图标文件依赖；未读数变化时重绘角标。
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

_SIZE = 64


def _badge_font():
    """角标数字字体：TrueType 更大更清晰，失败回退 Pillow 默认点阵。"""
    for name in ("segoeuib.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, 24)
        except OSError:
            continue
    return ImageFont.load_default()


def base_icon() -> Image.Image:
    """蓝色圆角方块 + 白色信封。"""
    img = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 圆角底板
    d.rounded_rectangle([2, 2, _SIZE - 2, _SIZE - 2], radius=14, fill=(30, 100, 220, 255))
    # 信封：矩形 + 折线（信盖）
    ex0, ey0, ex1, ey1 = 12, 20, _SIZE - 12, _SIZE - 18
    d.rounded_rectangle([ex0, ey0, ex1, ey1], radius=5, fill=(255, 255, 255, 255))
    d.line([ex0 + 2, ey0 + 3, (_SIZE // 2), (ey0 + ey1) // 2], fill=(30, 100, 220, 255), width=4)
    d.line([(_SIZE // 2), (ey0 + ey1) // 2, ex1 - 2, ey0 + 3], fill=(30, 100, 220, 255), width=4)
    return img


def with_badge(count: int) -> Image.Image:
    """在基础图标右上角叠加红色未读角标（>99 显示 99+）。"""
    img = base_icon()
    if count <= 0:
        return img
    d = ImageDraw.Draw(img)
    label = "99+" if count > 99 else str(count)
    # 角标圆的半径随位数微调
    r = 13 if len(label) == 1 else (17 if len(label) == 2 else 21)
    cx, cy = _SIZE - r - 2, r + 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(230, 50, 50, 255),
              outline=(255, 255, 255, 255), width=2)
    # 文字居中（缓存字体避免每次重绘都扫字体文件）
    global _FONT_CACHE
    try:
        font = _FONT_CACHE
    except NameError:
        font = _FONT_CACHE = _badge_font()
    bbox = d.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]), label,
           fill=(255, 255, 255, 255), font=font)
    return img
