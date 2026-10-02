# -*- coding: utf-8 -*-
"""邮件图片加载（v1.10.0，修复「无法观看图片」）。

流程：htmltext 渲染时记录 <img> 占位 → 本模块后台线程取图（CID 内嵌从原文
解出；http(s) 限流下载）→ 字节回主线程解码成 PhotoImage 插入。

资源与安全约束：
- 远程图仅 http/https，每张 ≤ 3MB、每封最多 10 张、总超时可控（10s/张）
- 按魔数校验真实是 PNG/JPEG/GIF，拒绝伪装内容
- 解码用 Pillow（托盘图标已在用，零新增依赖）；超宽缩到 640px，防巨图撑爆 Text
- 网络全在后台线程；tkinter 的 PhotoImage 创建/插入只在主线程（调用方负责）
"""
from __future__ import annotations

import base64
import io
import re
import urllib.parse
import urllib.request

# 每张图大小上限 / 单封最多张数 / 图片显示最大宽度 / 解码像素上限
MAX_IMG_BYTES = 3 * 1024 * 1024
MAX_IMAGES = 10
MAX_DISPLAY_W = 640
MAX_PIXELS = 12_000_000        # 超 1200 万像素拒显（防解码炸弹冻住 UI）
_DOWNLOAD_TIMEOUT = 10

_MAGIC = (b"\x89PNG", b"\xff\xd8", b"GIF8")


def _is_webp(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


class ImageItem:
    """一个待显示的图片：mark 为 Text 里的插入位置标记。"""
    __slots__ = ("mark", "src", "cid")

    def __init__(self, mark: str, src: str):
        self.mark = mark
        self.src = (src or "").strip()
        self.cid = self.src.lower().startswith("cid:")


def collect_images(html: str) -> list[ImageItem]:
    """从 HTML 里抽 <img src>（htmltext 渲染时逐个登记，这里是兜底/测试用）。"""
    out = []
    for m in re.finditer(r"(?is)<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", html):
        out.append(ImageItem("", m.group(1)))
        if len(out) >= MAX_IMAGES:
            break
    return out


def valid_image(data: bytes) -> bool:
    # bytes.startswith 接受元组：PNG/JPEG/GIF 魔数一查全包；WebP 单独判
    return bool(data) and (data[:4].startswith(_MAGIC) or _is_webp(data))


def download(url: str) -> bytes:
    """下载一张远程图片。仅 http/https；大小超限即弃。"""
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError("scheme")
    req = urllib.request.Request(url, headers={
        "User-Agent": "OneMail/1.10 (+image)",
        "Accept": "image/png,image/jpeg,image/gif,*/*;q=0.5",
    })
    with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp:
        data = resp.read(MAX_IMG_BYTES + 1)
    if len(data) > MAX_IMG_BYTES:
        raise ValueError("too large")
    if not valid_image(data):
        raise ValueError("not an image")
    return data


_CID_RE = re.compile(r"(?i)^cid:\s*(.+)$")


def cid_map_from_raw(raw: bytes) -> dict[str, bytes]:
    """从邮件原文解析 Content-ID -> 图片字节（仅取 image/* 且尺寸合规的部分）。"""
    from email import policy
    from email.parser import BytesParser
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw)
    except Exception:
        return {}
    out: dict[str, bytes] = {}
    try:
        for part in msg.walk():
            ctype = part.get_content_type()
            if not ctype.startswith("image/"):
                continue
            cid = str(part.get("Content-ID", "") or "").strip()
            if cid.startswith("<") and cid.endswith(">"):
                cid = cid[1:-1]
            if not cid:
                continue
            try:
                data = part.get_payload(decode=True) or b""
            except Exception:
                continue
            if data and len(data) <= MAX_IMG_BYTES and valid_image(data):
                out[cid.lower()] = data
    except Exception:
        pass
    return out


def cid_from_src(src: str) -> str:
    m = _CID_RE.match(src.strip())
    return m.group(1).strip() if m else ""


def data_b64_from_src(src: str) -> bytes | None:
    """data: URI 的图片（部分邮件内联 base64；兼容 URL-safe 变体）。"""
    if not src.lower().startswith("data:image/"):
        return None
    try:
        head, b64 = src.split(",", 1)
        # URL-safe 字母表（-_）先归一化，否则标准解码会静默丢字符
        b64 = b64.replace("-", "+").replace("_", "/")
        data = base64.b64decode(b64 + "===", validate=False)
        if data and len(data) <= MAX_IMG_BYTES and valid_image(data):
            return data
    except Exception:
        pass
    return None


def decode(data: bytes):
    """字节 → 缩放好的 PIL.Image（**后台线程**调用）。

    像素总数超 MAX_PIXELS 直接拒绝：Pillow 对超大图的全量解码在主线程
    会冻结 UI 数百毫秒到数秒（v1.10.1 审查修复）。失败返回 None。
    """
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        if im.width * im.height > MAX_PIXELS:
            return None
        im.load()
        if im.width > MAX_DISPLAY_W:
            h = max(1, round(im.height * MAX_DISPLAY_W / im.width))
            im = im.resize((MAX_DISPLAY_W, h))
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        return im
    except Exception:
        return None


def photo_from(im):
    """PIL.Image → Tk PhotoImage（**主线程**调用，tkinter 非线程安全）。"""
    try:
        from PIL import ImageTk
        return ImageTk.PhotoImage(im)
    except Exception:
        return None


def to_photo(data: bytes):
    """便捷版：decode + photo_from（仅适合已在主线程拿到的数据）。"""
    im = decode(data)
    return photo_from(im) if im is not None else None
