# tests/test_recorder_types.py
"""recorder 模块数据结构单测。"""
from recorder.types import NormalizedEvent, Segment, DistillResult, TraceEnvelope


def test_normalized_event_defaults():
    """NormalizedEvent 仅 type/url/ts 必填，其余可选。"""
    e = NormalizedEvent(type="click", url="https://example.com", ts=1000)
    assert e.type == "click"
    assert e.target_tag is None
    assert e.value is None


def test_segment_has_extension_fields():
    """Segment 预留 bucket_id/capability 扩展字段（初版置空）。"""
    seg = Segment(
        segment_id="t1::0::5",
        source_track_id="t1",
        domain="example.com",
        start_idx=0,
        end_idx=5,
        events=[],
        boundary_reason="end_of_track",
        entry_url="https://example.com",
        exit_url="https://example.com/done",
        duration_ms=5000,
        event_summary="click ...",
    )
    assert seg.bucket_id is None
    assert seg.capability is None


def test_distill_result_fields():
    """DistillResult 含 skill_name/description/skill_md（注入 frontmatter 用）。"""
    r = DistillResult(
        skill_name="login-flow",
        description="登录网站",
        skill_md="# 登录\n\n步骤...",
    )
    assert r.skill_name == "login-flow"
    assert isinstance(r.skill_md, str)


def test_trace_envelope_minimal():
    """TraceEnvelope 含 schema_version/trace_id/events 等核心字段。"""
    env = TraceEnvelope(
        schema_version="journey_trace_v1",
        trace_id="t1",
        started_at="2026-06-28T00:00:00Z",
        label="测试",
    )
    assert env.events == []
    assert env.summary["domains"] == []
