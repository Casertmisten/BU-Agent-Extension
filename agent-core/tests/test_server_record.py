# tests/test_server_record.py
"""server.py 录制路由单测。"""
import asyncio
import json
import pytest
from unittest.mock import MagicMock
from pathlib import Path

import server
from browser.connection import BrowserConnection


class FakeWS:
    def __init__(self, messages):
        self._messages = iter(messages)
        self.sent = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._messages)
        except StopIteration:
            raise StopAsyncIteration

    async def send(self, data):
        self.sent.append(data)


def _mock_agent():
    agent = MagicMock()
    agent._busy = False
    agent._current_ws = None
    agent.conn = BrowserConnection()
    async def _list_skills(): return []
    agent.list_skills = _list_skills
    return agent


@pytest.mark.asyncio
async def test_record_start_creates_session(monkeypatch):
    """record_start 应创建录制会话并回 record_started。"""
    agent = _mock_agent()
    server._agent = agent
    server._current_task = None
    monkeypatch.setattr(server, "_record_sessions", {})

    try:
        ws = FakeWS([json.dumps({"type": "record_start", "tab_id": 1, "label": "测试"})])
        await server.handle_client(ws, {"skills": {"dirs": ["./skills"]}})

        started = [json.loads(s) for s in ws.sent if json.loads(s).get("type") == "record_started"]
        assert len(started) == 1
        assert "trace_id" in started[0]
        assert started[0]["trace_id"] in server._record_sessions
    finally:
        server._agent = None
        server._current_task = None


@pytest.mark.asyncio
async def test_record_start_uses_client_trace_id(monkeypatch):
    """前端携带 trace_id 时，后端必须复用该 trace_id（不能自己生成新的）。

    回归测试：background 生成的 trace_id 与 content 上传事件用的 trace_id 必须一致，
    否则 record_event 找不到 session。
    """
    agent = _mock_agent()
    server._agent = agent
    server._current_task = None
    monkeypatch.setattr(server, "_record_sessions", {})

    try:
        ws = FakeWS([json.dumps({
            "type": "record_start", "tab_id": 1, "label": "测试", "trace_id": "fixedtid1234",
        })])
        await server.handle_client(ws, {"skills": {"dirs": ["./skills"]}})

        assert "fixedtid1234" in server._record_sessions
        started = [json.loads(s) for s in ws.sent if json.loads(s).get("type") == "record_started"]
        assert started[0]["trace_id"] == "fixedtid1234"
    finally:
        server._agent = None
        server._current_task = None


@pytest.mark.asyncio
async def test_record_event_appends_to_session(monkeypatch):
    """record_event 应把事件追加到对应 session。"""
    agent = _mock_agent()
    server._agent = agent
    server._current_task = None

    sessions = {"t1": {"events": [], "label": "", "tab_id": 1}}
    monkeypatch.setattr(server, "_record_sessions", sessions)

    try:
        ws = FakeWS([json.dumps({
            "type": "record_event",
            "trace_id": "t1",
            "events": [{"kind": "action", "action_type": "click", "url": "https://x.com", "timestamp": 0}],
            "seq": 1,
        })])
        await server.handle_client(ws, {"skills": {"dirs": ["./skills"]}})

        assert len(sessions["t1"]["events"]) == 1
        progress = [json.loads(s) for s in ws.sent if json.loads(s).get("type") == "record_progress"]
        assert progress[0]["received_events"] == 1
    finally:
        server._agent = None
        server._current_task = None


@pytest.mark.asyncio
async def test_record_stop_keeps_session_and_replies_summary(monkeypatch):
    """record_stop 应保留 session（不蒸馏），回 record_stopped 携带摘要。"""
    agent = _mock_agent()
    server._agent = agent
    server._current_task = None

    sessions = {"t1": {"events": [
        {"kind": "action", "action_type": "click", "url": "https://x.com", "timestamp": 1000},
        {"kind": "action", "action_type": "click", "url": "https://x.com", "timestamp": 3000},
    ], "label": "", "tab_id": 1}}
    monkeypatch.setattr(server, "_record_sessions", sessions)

    try:
        ws = FakeWS([json.dumps({"type": "record_stop", "trace_id": "t1", "label": "登录"})])
        await server.handle_client(ws, {"skills": {"dirs": ["./skills"]}})

        stopped = [json.loads(s) for s in ws.sent if json.loads(s).get("type") == "record_stopped"]
        assert len(stopped) == 1
        assert stopped[0]["trace_id"] == "t1"
        assert stopped[0]["event_count"] == 2
        assert "x.com" in stopped[0]["domains"]
        # session 仍在内存（等用户确认蒸馏）
        assert "t1" in server._record_sessions
        assert server._record_sessions["t1"]["label"] == "登录"
    finally:
        server._agent = None
        server._current_task = None


@pytest.mark.asyncio
async def test_record_distill_triggers_pipeline(monkeypatch, tmp_path):
    """record_distill 应从 session 取事件触发蒸馏，并清理 session。"""
    agent = _mock_agent()
    server._agent = agent
    server._current_task = None

    sessions = {"t1": {"events": [
        {"kind": "action", "action_type": "click", "url": "https://x.com", "timestamp": 0}
    ], "label": "测试", "tab_id": 1}}
    monkeypatch.setattr(server, "_record_sessions", sessions)

    captured = {}

    async def _fake_pipeline(trace_id, raw_events, label, model, skills_root, on_progress=None, **kw):
        captured["trace_id"] = trace_id
        captured["events_count"] = len(raw_events)
        return {"skill_name": "test-skill", "skill_path": str(skills_root / "test-skill" / "SKILL.md")}

    monkeypatch.setattr("server.run_distill_pipeline", _fake_pipeline)

    try:
        ws = FakeWS([json.dumps({"type": "record_distill", "trace_id": "t1", "label": "登录"})])
        await server.handle_client(ws, {
            "skills": {"dirs": [str(tmp_path / "skills")]},
            "llm": {"provider": "dashscope", "model": "x", "api_key": "k"},
        })

        await asyncio.sleep(0.2)  # 等蒸馏 task

        assert captured.get("trace_id") == "t1"
        assert captured.get("events_count") == 1
        assert "t1" not in server._record_sessions  # session 已清理
    finally:
        server._agent = None
        server._current_task = None


@pytest.mark.asyncio
async def test_record_discard_removes_session(monkeypatch):
    """record_discard 应删除 session，不蒸馏。"""
    agent = _mock_agent()
    server._agent = agent
    server._current_task = None

    sessions = {"t1": {"events": [], "label": "", "tab_id": 1}}
    monkeypatch.setattr(server, "_record_sessions", sessions)

    try:
        ws = FakeWS([json.dumps({"type": "record_discard", "trace_id": "t1"})])
        await server.handle_client(ws, {"skills": {"dirs": ["./skills"]}})

        assert "t1" not in server._record_sessions
    finally:
        server._agent = None
        server._current_task = None
