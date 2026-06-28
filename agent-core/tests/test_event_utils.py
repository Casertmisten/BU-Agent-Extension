# tests/test_event_utils.py
"""event_utils 单测：归一化、摘要、脱敏。"""
from recorder.event_utils import (
    normalize_journey_event, summarize_events, registered_domain, redact, host_path,
)
from recorder.types import NormalizedEvent


def test_registered_domain():
    assert registered_domain("https://www.example.com/path") == "example.com"
    assert registered_domain("https://a.b.example.co.uk/p") == "co.uk"
    assert registered_domain("invalid") == ""


def test_redact_email():
    assert "<runtime-email>" in redact("联系我 user@example.com")


def test_redact_card():
    # 16 位数字（Luhn 有效：标准测试卡 4111111111111111）
    out = redact("卡号 4111111111111111")
    assert "<runtime-payment-card>" in out


def test_host_path_truncates_long_path():
    url = "https://example.com/" + "a" * 200
    hp = host_path(url)
    assert hp.endswith("...")
    assert len(hp) <= 120


def test_normalize_action_click():
    """journey_trace_v1 的 action 事件 → NormalizedEvent。"""
    raw = {
        "kind": "action",
        "action_type": "click",
        "url": "https://example.com",
        "timestamp": 5000,
        "target": {"tag": "button", "id": "btn1", "text": "提交", "xpath": "/html/body/button"},
        "coords": {"x": 10, "y": 20},
    }
    e = normalize_journey_event(raw, base_ts=1000)
    assert e is not None
    assert e.type == "click"
    assert e.ts == 4000
    assert e.target_tag == "button"
    assert e.target_text == "提交"


def test_normalize_action_dblclick_becomes_click():
    raw = {"kind": "action", "action_type": "dblclick", "url": "https://x.com", "timestamp": 0}
    e = normalize_journey_event(raw, base_ts=0)
    assert e.type == "click"


def test_normalize_skips_focus_blur():
    """focus/blur/contextmenu/copy/cut/selection 不参与蒸馏，返回 None。"""
    for at in ("focus", "blur", "contextmenu", "copy", "cut", "selection"):
        raw = {"kind": "action", "action_type": at, "url": "https://x.com", "timestamp": 0}
        assert normalize_journey_event(raw, base_ts=0) is None


def test_normalize_navigation_load():
    raw = {"kind": "navigation", "nav_type": "load", "to_url": "https://x.com/home", "timestamp": 0}
    e = normalize_journey_event(raw, base_ts=0)
    assert e.type == "pageLoad"
    assert e.url == "https://x.com/home"


def test_summarize_events_basic():
    events = [
        NormalizedEvent(type="pageLoad", url="https://example.com", ts=0),
        NormalizedEvent(type="click", url="https://example.com", ts=100, target_text="登录"),
        NormalizedEvent(type="input", url="https://example.com", ts=200, target_text="邮箱", value="a@b.com"),
    ]
    summary = summarize_events(events)
    assert "pageLoad" in summary
    assert "登录" in summary
    assert "<runtime-email>" in summary  # value 被脱敏


def test_summarize_repeats_collapsed():
    """连续相同点击应合并为 xN。"""
    events = [
        NormalizedEvent(type="click", url="https://x.com", ts=i * 100, target_text="下一页")
        for i in range(5)
    ]
    summary = summarize_events(events)
    assert "x5" in summary
