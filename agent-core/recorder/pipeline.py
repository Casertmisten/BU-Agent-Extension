# recorder/pipeline.py
"""蒸馏管线编排：atomize → distill → install。

提供异步入口 run_distill_pipeline，带进度回调，供 server.py 调用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from .atomizer import segment_trajectory
from .distiller import distill_segments
from .event_utils import normalize_journey_event, registered_domain
from .installer import install_skill
from .types import NormalizedEvent

ProgressCallback = Callable[[str, str], Awaitable[None]]


async def run_distill_pipeline(
    trace_id: str,
    raw_events: list[dict[str, Any]],
    label: str,
    model,
    skills_root: Path,
    on_progress: ProgressCallback | None = None,
    distill_retries: int = 1,
) -> dict[str, str]:
    """端到端蒸馏：原始事件 → SKILL.md。

    Args:
        trace_id: 轨迹 ID。
        raw_events: journey_trace_v1 格式的原始事件列表。
        label: 用户填写的任务标签。
        model: agentscope 模型实例。
        skills_root: skills 根目录。
        on_progress: 进度回调（stage, message）。
        distill_retries: 蒸馏失败重试次数。

    Returns:
        {"skill_name": ..., "skill_path": ...}

    Raises:
        ValueError: 切片后无有效段。
        RuntimeError: 蒸馏重试后仍失败。
    """
    async def _progress(stage: str, message: str) -> None:
        if on_progress:
            await on_progress(stage, message)

    # ---- atomize ----
    await _progress("atomize", "正在分析操作步骤...")

    # 归一化事件
    base_ts = min((e.get("timestamp", 0) for e in raw_events), default=0) if raw_events else 0
    normalized: list[NormalizedEvent] = []
    for raw in raw_events:
        ev = normalize_journey_event(raw, base_ts)
        if ev is not None:
            normalized.append(ev)
    normalized.sort(key=lambda e: e.ts)

    if not normalized:
        raise ValueError("未捕获到有效操作，请重新录制")

    # 推导 track_domain（首个事件的域名）
    track_domain = registered_domain(normalized[0].url) if normalized else ""

    segments = segment_trajectory(trace_id, track_domain, normalized)
    if not segments:
        raise ValueError("未捕获到有效操作，请重新录制")

    await _progress("atomize", f"已识别 {len(segments)} 个操作段落")

    # ---- distill ----
    await _progress("distill", "正在蒸馏技能手册...")

    last_err: Exception | None = None
    result = None
    for attempt in range(distill_retries + 1):
        try:
            result = await distill_segments(segments, model, label)
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < distill_retries:
                await _progress("distill", f"蒸馏失败，重试中... ({attempt + 1}/{distill_retries})")
            continue

    if result is None:
        raise RuntimeError(f"蒸馏失败：{last_err}")

    # ---- install ----
    await _progress("install", "正在写入技能文件...")

    installed = install_skill(
        result=result,
        skills_root=skills_root,
        trace_events=raw_events,
        trace_id=trace_id,
    )

    await _progress("install", f"技能 {installed['skill_name']} 已生成")

    return installed
