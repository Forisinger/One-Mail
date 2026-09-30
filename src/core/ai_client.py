# -*- coding: utf-8 -*-
"""AI 客户端（v1.9.0）：OpenAI 兼容 /chat/completions，纯标准库实现。

设计要点：
- 零第三方依赖（urllib + json），DeepSeek / OpenAI / 通义等任何 OpenAI
  兼容端点均可，用户在设置里自填 base_url / model / key。
- build_request 可离线单测；chat 供后台线程调用，UI 线程绝不碰网络。
- 不用流式：一次响应内存可控（总结/写信输出通常几 KB），实现更简单可靠。
- API Key 不在这里存储：调用方经 core.security（DPAPI）读写。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

TIMEOUT = 90


def build_request(base_url: str, api_key: str, model: str,
                  messages: list[dict], timeout: int = TIMEOUT) -> urllib.request.Request:
    """组装 OpenAI 兼容 chat/completions 请求（可离线单测）。"""
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url:
        raise ValueError("API 地址为空")
    if not base_url.endswith("/chat/completions"):
        base_url += "/chat/completions"
    if not (api_key or "").strip():
        raise ValueError("API Key 为空")
    payload = json.dumps({
        "model": model or "gpt-4o-mini",
        "messages": messages,
        "temperature": 0.7,
    }).encode("utf-8")
    req = urllib.request.Request(
        base_url, data=payload, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key.strip()}",
        })
    return req


def chat(base_url: str, api_key: str, model: str, messages: list[dict],
         timeout: int = TIMEOUT) -> str:
    """发起对话，返回首条回复文本。失败抛异常（由调用方提示）。"""
    req = build_request(base_url, api_key, model, messages, timeout)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code} {detail}") from e
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"响应格式异常: {data!r:.200}") from e


def summarize(base_url: str, api_key: str, model: str,
              subject: str, sender: str, body: str) -> str:
    """总结一封邮件。"""
    body = (body or "")[:12000]   # 控制请求体大小，超长截断
    prompt = (
        "请用简洁的中文总结这封邮件的要点，包括：主要事项、需要我处理的内容、"
        "关键时间点（如有）。直接输出总结，不要开场白。\n\n"
        f"主题：{subject}\n发件人：{sender}\n\n正文：\n{body}")
    return chat(base_url, api_key, model,
                [{"role": "user", "content": prompt}])


def draft(base_url: str, api_key: str, model: str, instruction: str,
          context: str = "") -> str:
    """按用户要求起草邮件正文。"""
    instruction = (instruction or "").strip()
    if not instruction:
        raise ValueError("写作要求为空")
    system = (
        "你是一封中文电子邮件的代笔助手。根据用户要求写出邮件正文，"
        "语气专业自然。直接输出正文内容，不要包含主题行，"
        "不要任何解释、开场白或 Markdown 代码块标记。")
    user = instruction
    if context.strip():
        user += "\n\n（参考上下文）\n" + context.strip()[:8000]
    return chat(base_url, api_key, model,
                [{"role": "system", "content": system},
                 {"role": "user", "content": user}])
