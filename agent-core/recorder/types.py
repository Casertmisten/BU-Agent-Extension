# recorder/types.py
"""录制蒸馏管线的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NormalizedEvent:
    """归一化后的单个事件（从 journey_trace_v1 的 action/navigation 转换）。"""
    type: str
    url: str
    ts: int
    target_tag: str | None = None
    target_id: str | None = None
    target_text: str | None = None
    target_xpath: str | None = None
    value: str | None = None
    key: str | None = None
    x: int | None = None
    y: int | None = None


@dataclass
class TraceEnvelope:
    """一条完整录制轨迹的外壳。"""
    schema_version: str
    trace_id: str
    started_at: str
    label: str = ""
    description: str = ""
    events: list[NormalizedEvent] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=lambda: {
        "domains": [],
        "duration_ms": 0,
        "event_counts": {},
    })


@dataclass
class Segment:
    """atomizer 切出的语义段。

    bucket_id/capability 为扩展接口预留（初版置空），未来 classify/bucket 阶段填充。
    """
    segment_id: str
    source_track_id: str
    domain: str
    start_idx: int
    end_idx: int
    events: list[NormalizedEvent]
    boundary_reason: str
    entry_url: str
    exit_url: str
    duration_ms: int
    event_summary: str
    # 扩展接口：未来归并用
    bucket_id: str | None = None
    capability: str | None = None


@dataclass
class DistillResult:
    """蒸馏产物：注入 SKILL.md frontmatter 用。"""
    skill_name: str
    description: str
    skill_md: str
