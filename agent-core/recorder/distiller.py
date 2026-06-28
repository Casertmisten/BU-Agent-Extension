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
- 务必简洁：全文不超过 30 行，避免冗长解释

重要：只输出 JSON，不要在 JSON 前后添加任何说明文字。
skill_md 中的换行用 \\n 转义，确保整个 JSON 合法可解析。
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
    """从模型输出解析 JSON，容错处理 code fence、包裹文本和截断。

    照搬 Browser-BC harness/llm.py 的 parse_json_from_model 逻辑，
    并增加截断容错：当 skill_md 值因 token 上限被截断导致 JSON 不完整时，
    用正则逐字段提取（skill_md 取已有截断内容，总比丢弃整条蒸馏结果好）。
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

    # 截断容错：JSON 不完整（如 skill_md 值被 token 上限截断）时，
    # 用正则逐字段提取。各字段的 "key": "value" 结构通常完整，只有最后一个值被截断。
    recovered = _recover_truncated_fields(cleaned)
    if recovered:
        return recovered

    raise ValueError(f"无法解析模型输出为 JSON: {text[:200]}...")


def _unescape_json_string(s: str) -> str:
    """对 JSON 字符串值做有限转义还原（\\n→换行 等），不破坏 UTF-8 原文。

    比 unicode_escape 安全：后者会把 UTF-8 字节序列当 Latin-1 处理导致中文乱码。
    """
    return (
        s.replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\r", "\r")
        .replace('\\"', '"')
        .replace("\\\\", "\\")
    )


def _recover_truncated_fields(text: str) -> dict[str, Any] | None:
    """从被截断的 JSON 文本中逐字段提取。

    匹配 "skill_name": "..." / "description": "..." / "skill_md": "..."，
    即使整体 JSON 因截断无法解析，也能抢救出已有内容。
    """
    result: dict[str, Any] = {}
    # 匹配 "key": "value"，value 可含转义引号；未闭合的 value（截断）也尽量取到末尾
    for key in ("skill_name", "description", "skill_md"):
        # 优先匹配闭合字符串："key": "value"
        m = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        if m:
            result[key] = _unescape_json_string(m.group(1))
            continue
        # 未闭合（截断）："key": "value...（到文本末尾）
        m = re.search(rf'"{key}"\s*:\s*"(.*)$', text, re.DOTALL)
        if m:
            result[key] = _unescape_json_string(m.group(1).strip())
    # 至少要拿到 skill_md 或 skill_name 才算恢复成功
    if "skill_md" in result or "skill_name" in result:
        result.setdefault("skill_name", "recorded-skill")
        result.setdefault("description", "")
        result.setdefault("skill_md", "")
        return result
    return None


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

    # agentscope model 的 __call__ 是 async def：
    #   - 调用 model([...]) 返回 coroutine
    #   - await 后得到 ChatResponse（非流式）或 AsyncGenerator[ChatResponse]（流式，默认）
    text_buf = ""
    resp_or_gen = await model([
        SystemMsg(name="system", content=DISTILL_SYSTEM),
        UserMsg(name="user", content=prompt),
    ])
    if hasattr(resp_or_gen, "__aiter__"):
        # 流式：逐 chunk 累加增量 text
        async for resp in resp_or_gen:
            for block in resp.content:
                text = getattr(block, "text", None)
                if text:
                    text_buf += text
    else:
        # 非流式：直接取完整 content
        for block in resp_or_gen.content:
            text = getattr(block, "text", None)
            if text:
                text_buf += text

    data = parse_skill_json(text_buf)

    return DistillResult(
        skill_name=data.get("skill_name", "recorded-skill"),
        description=data.get("description", ""),
        skill_md=data.get("skill_md", ""),
    )
