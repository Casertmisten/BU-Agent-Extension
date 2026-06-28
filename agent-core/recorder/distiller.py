# recorder/distiller.py
"""LLM 蒸馏：把录制段蒸馏为 SKILL.md。

参考 Browser-BC harness/distiller.py，简化为 skill_name/description/skill_md 三字段。
LLM 调用复用 agentscope model（__call__ 返回 async generator of ChatResponse）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from agentscope.message import SystemMsg, UserMsg

from .types import Segment, DistillResult

DISTILL_SYSTEM = (
    "你是浏览器操作技能蒸馏专家。将用户录制的事件序列提炼为"
    "AI Agent 可执行的自然语言操作手册。"
)

DISTILL_PROMPT_TEMPLATE = """\
## 录制信息
标签：{label}
涉及域名：{domains}
事件总数：{event_count}

## 事件序列（已脱敏）
{events_summary}

## 任务
将上述操作提炼为一份可复用的技能手册。输出 JSON：
{{
  "skill_name": "kebab-case 名称（如 search-and-add-to-cart）",
  "description": "一句话描述技能用途（≤80字，用于 Agent 触发匹配）",
  "skill_md": "完整 markdown 正文（不含 frontmatter）"
}}

skill_md 要求：
- 聚焦「做什么」而非「点哪里」，不要写死 CSS 选择器或 xpath
- 用"点击登录按钮""输入用户名"这样的自然语言描述
- 覆盖：前置条件、关键步骤（有序列表）、终止条件
- 通用化：适用于同类网站，不只针对录制的那一个
"""


def build_distill_prompt(segments: list[Segment], label: str = "") -> str:
    """构建蒸馏 prompt：合并所有段的事件摘要。"""
    domains = sorted({s.domain for s in segments})
    total_events = sum(len(s.events) for s in segments)
    # 多段时拼接各段摘要，用分隔标注域名
    if len(segments) == 1:
        summary = segments[0].event_summary
    else:
        parts = []
        for i, seg in enumerate(segments):
            parts.append(f"### 段 {i + 1}（域名：{seg.domain}）\n{seg.event_summary}")
        summary = "\n\n".join(parts)

    return DISTILL_PROMPT_TEMPLATE.format(
        label=label or "（无）",
        domains=", ".join(domains) or "未知",
        event_count=total_events,
        events_summary=summary,
    )


def _escape_invalid_json_backslashes(text: str) -> str:
    """修复模型输出中无效的反斜杠转义。"""
    valid_escapes = set('"\\/bfnrtu')
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt not in valid_escapes:
                out.append("\\\\")
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def parse_skill_json(text: str) -> dict[str, Any]:
    """从模型输出解析 JSON，容错处理 code fence 和包裹文本。

    照搬 Browser-BC harness/llm.py 的 parse_json_from_model 逻辑。
    """
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"```$", "", cleaned).strip()

    # strict=False 允许 JSON 字符串值中的原始控制字符（模型常返回未转义换行）
    for s in (cleaned, _escape_invalid_json_backslashes(cleaned)):
        try:
            return json.loads(s, strict=False)
        except json.JSONDecodeError:
            pass

    # 尝试提取第一个 {...} 块
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        body = cleaned[start : end + 1]
        for s in (body, _escape_invalid_json_backslashes(body)):
            try:
                return json.loads(s, strict=False)
            except json.JSONDecodeError:
                pass

    raise ValueError(f"无法解析模型输出为 JSON: {text[:200]}...")


async def distill_segments(
    segments: list[Segment],
    model,
    label: str = "",
) -> DistillResult:
    """调用 LLM 蒸馏段列表为 DistillResult。

    model 是 agentscope 模型实例（__call__ 返回 async generator of ChatResponse）。
    失败时抛 ValueError（由调用方决定重试/降级）。
    """
    if not segments:
        raise ValueError("无段可蒸馏")

    prompt = build_distill_prompt(segments, label)

    # agentscope model 的 __call__ 是 async def，流式模式下返回 AsyncGenerator[ChatResponse]，
    # 每个 chunk 的 content 是增量 TextBlock；非流式则直接返回 ChatResponse。
    # 统一用 async for 消费（非流式 ChatResponse 不是 async iterable，单独 await 处理）。
    result = model([
        SystemMsg(name="system", content=DISTILL_SYSTEM),
        UserMsg(name="user", content=prompt),
    ])
    text_buf = ""
    if hasattr(result, "__aiter__"):
        async for resp in result:
            for block in resp.content:
                text = getattr(block, "text", None)
                if text:
                    text_buf += text
    else:
        # 非流式：result 是 coroutine，await 拿 ChatResponse
        resp = await result
        for block in resp.content:
            text = getattr(block, "text", None)
            if text:
                text_buf += text

    data = parse_skill_json(text_buf)

    return DistillResult(
        skill_name=data.get("skill_name", "recorded-skill"),
        description=data.get("description", ""),
        skill_md=data.get("skill_md", ""),
    )
