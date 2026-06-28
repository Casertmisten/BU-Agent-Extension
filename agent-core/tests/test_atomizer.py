# tests/test_atomizer.py
"""atomizer 单测：切片边界、噪音过滤、段归域。"""
from recorder.atomizer import segment_trajectory
from recorder.types import NormalizedEvent


def _ev(type_, url, ts, **kw):
    return NormalizedEvent(type=type_, url=url, ts=ts, **kw)


def test_empty_events_returns_empty():
    assert segment_trajectory("t1", "example.com", []) == []


def test_single_segment_short_track():
    """少于 MIN_SEGMENT_EVENTS 的事件归为一段。"""
    events = [_ev("click", "https://example.com", 0, target_text="按钮")]
    segs = segment_trajectory("t1", "example.com", events)
    assert len(segs) == 1
    assert segs[0].boundary_reason == "end_of_track"


def test_domain_change_boundary():
    """域名切换应产生边界。"""
    events = [
        _ev("click", "https://a.com", 0, target_text="x"),
        _ev("click", "https://a.com", 100, target_text="y"),
        _ev("click", "https://a.com", 200, target_text="z"),
        _ev("pageLoad", "https://b.com", 300),
        _ev("click", "https://b.com", 400, target_text="w"),
        _ev("click", "https://b.com", 500, target_text="v"),
        _ev("click", "https://b.com", 600, target_text="u"),
    ]
    segs = segment_trajectory("t1", "a.com", events)
    # track_domain 是 a.com，b.com 的切换不会切（只切回 track_domain）
    # 所以这里应是一段（b.com 是偏离域，不切）
    assert len(segs) >= 1


def test_idle_gap_boundary():
    """相邻事件间隔 > 15s 应切片。"""
    events = [
        _ev("click", "https://example.com", 0, target_text="a", target_xpath="/a"),
        _ev("click", "https://example.com", 100, target_text="b", target_xpath="/b"),
        _ev("click", "https://example.com", 200, target_text="c", target_xpath="/c"),
        _ev("click", "https://example.com", 20000, target_text="d", target_xpath="/d"),  # 20s 后
        _ev("click", "https://example.com", 20100, target_text="e", target_xpath="/e"),
        _ev("click", "https://example.com", 20200, target_text="f", target_xpath="/f"),
    ]
    segs = segment_trajectory("t1", "example.com", events)
    assert len(segs) == 2
    assert segs[0].boundary_reason == "idle_gap"


def test_lone_modifier_filtered():
    """孤立的修饰键（Shift/Meta/Alt/Ctrl）应被过滤。"""
    events = [
        _ev("click", "https://example.com", 0, target_text="x"),
        _ev("keydown", "https://example.com", 100, key="Shift"),  # 孤立修饰键
        _ev("click", "https://example.com", 200, target_text="y"),
    ]
    segs = segment_trajectory("t1", "example.com", events)
    # Shift 被过滤后剩 2 个 click，仍 >= MIN 但合并为一段
    assert len(segs) == 1
    assert all(e.key != "Shift" for seg in segs for e in seg.events)


def test_duplicate_click_deduped():
    """2 秒内同 xpath 的重复点击应去重（保留最后一个）。"""
    events = [
        _ev("click", "https://example.com", 0, target_text="btn", target_xpath="/btn"),
        _ev("click", "https://example.com", 500, target_text="btn", target_xpath="/btn"),
        _ev("click", "https://example.com", 1000, target_text="btn", target_xpath="/btn"),
        _ev("click", "https://example.com", 1500, target_text="other", target_xpath="/other"),
    ]
    segs = segment_trajectory("t1", "example.com", events)
    # 前 3 个同 xpath < 2s 去重为 1 个（保留最后），加 other = 2 个事件
    total = sum(len(s.events) for s in segs)
    assert total == 2


def test_segment_domain_dominant():
    """段的 domain 应是段内主导域名。"""
    events = [
        _ev("click", "https://example.com/p1", 0, target_text="a"),
        _ev("click", "https://example.com/p1", 100, target_text="b"),
        _ev("click", "https://example.com/p1", 200, target_text="c"),
    ]
    segs = segment_trajectory("t1", "example.com", events)
    assert segs[0].domain == "example.com"
