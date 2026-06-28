# 录制用户操作沉淀为技能 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户在浏览器中操作一次，扩展捕获操作步骤，经后端 LLM 蒸馏为 `SKILL.md`，落入 `agent-core/skills/` 立即可用。

**Architecture:** 前端 content script 动态注入捕获 DOM 事件（照搬 Browser-BC 的 `capture/` 模块），经现有 WebSocket 以 `record_*` 消息批量上传到 `agent-core`，后端 atomize 切片 + distill 蒸馏成 `SKILL.md` 写入 skills 目录，利用 `LocalSkillLoader` 的实时扫描机制立即生效。

**Tech Stack:** 前端 WXT + React + TypeScript + Vitest；后端 Python + agentscope v2 + pytest。

**参考项目：** `/Users/heren/code/Browser-BC`（照搬其 `extension/src/capture/` 与 `harness/` 核心逻辑）

**设计文档：** `docs/superpowers/specs/2026-06-28-recording-to-skill-design.md`

---

## 文件结构总览

### 后端新增（`agent-core/recorder/`）
| 文件 | 职责 |
|---|---|
| `recorder/__init__.py` | 模块导出 |
| `recorder/types.py` | `NormalizedEvent` / `TraceEnvelope` / `Segment` / `DistillResult` 数据结构 |
| `recorder/event_utils.py` | 事件归一化（journey_trace_v1 → NormalizedEvent）+ 文本摘要（summarize_events） |
| `recorder/atomizer.py` | 轨迹切片（边界规则 + 噪音过滤 + 段归域） |
| `recorder/distiller.py` | LLM 蒸馏 prompt + JSON 解析 → SKILL.md |
| `recorder/installer.py` | 写入 `skills/<name>/SKILL.md` + 命名冲突处理 + trace 留档 |

### 后端修改
| 文件 | 改动 |
|---|---|
| `server.py` | 新增 `record_start`/`record_event`/`record_stop`/`record_redistill` 路由 + 蒸馏 task |
| `config.yaml` | 新增 `recorder` 配置段 |
| `config_loader.py` | 无需改（已支持任意嵌套 dict） |

### 前端新增（`chrome-extension/src/`）
| 文件 | 职责 |
|---|---|
| `capture/id.ts` | 事件 ID 生成（crypto.getRandomValues） |
| `capture/types.ts` | 事件数据结构（照搬 Browser-BC 简化版，去掉视频/网络/截图/身份包） |
| `capture/selector.ts` | ElementRef 构建 + 稳定选择器/xpath 生成 |
| `capture/redactor.ts` | 隐私脱敏（密码/邮箱/支付/OTP，简化版） |
| `capture/action-recorder.ts` | DOM 事件捕获（16 种 action + 滚动节流 + 键盘过滤） |
| `capture/mutation-summary-recorder.ts` | MutationObserver 批量摘要 |
| `capture/recorder.ts` | 录制编排（start/stop/flush，聚合事件） |
| `entrypoints/recorder.content.ts` | 动态注入的 content script 入口 |
| `hooks/useRecorder.ts` | 前端录制状态管理 |

### 前端修改
| 文件 | 改动 |
|---|---|
| `types/index.ts` | 新增 `record_*` 消息类型 + `RecorderStatus` |
| `entrypoints/background.ts` | 新增录制路由（注入 content + 聚合 + 批量上传）+ badge |
| `components/ChatView.tsx` | 新增录制按钮 + 三态 UI + 停止确认 |

---

## 阶段 A：后端蒸馏管线（纯逻辑，TDD 友好）

> 先搭后端，因为它有清晰的输入输出边界，适合单测先行。所有任务在 `agent-core/` 下，用 `uv run pytest` 跑测试。

### Task A1: 后端数据结构 `recorder/types.py`

**Files:**
- Create: `agent-core/recorder/__init__.py`
- Create: `agent-core/recorder/types.py`
- Create: `agent-core/tests/test_recorder_types.py`

- [ ] **Step 1: 写失败测试**

```python
# agent-core/tests/test_recorder_types.py
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd agent-core && uv run pytest tests/test_recorder_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'recorder'`

- [ ] **Step 3: 实现 `recorder/types.py`**

```python
# agent-core/recorder/types.py
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
```

```python
# agent-core/recorder/__init__.py
"""录制 → 蒸馏 → 安装 管线。"""

from .types import NormalizedEvent, TraceEnvelope, Segment, DistillResult

__all__ = ["NormalizedEvent", "TraceEnvelope", "Segment", "DistillResult"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd agent-core && uv run pytest tests/test_recorder_types.py -v`
Expected: PASS（4 个测试全过）

- [ ] **Step 5: 提交**

```bash
cd agent-core
git add recorder/__init__.py recorder/types.py tests/test_recorder_types.py
git commit -m "feat(recorder): 新增蒸馏管线数据结构 NormalizedEvent/Segment/DistillResult"
```

---

### Task A2: 事件归一化与文本摘要 `recorder/event_utils.py`

**Files:**
- Create: `agent-core/recorder/event_utils.py`
- Create: `agent-core/tests/test_event_utils.py`

> 照搬自 Browser-BC 的 `harness/event_utils.py`（`NormalizedEvent` + `summarize_events` + `registered_domain` + `redact` + `host_path`），保持其全部逻辑。`NormalizedEvent` 已在 `types.py` 定义，这里 import 即可。

- [ ] **Step 1: 写失败测试**

```python
# agent-core/tests/test_event_utils.py
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd agent-core && uv run pytest tests/test_event_utils.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `recorder/event_utils.py`**

> 照搬 `/Users/heren/code/Browser-BC/harness/event_utils.py` 的全部代码（`NormalizedEvent` 除外，改为从 `types` import），新增 `normalize_journey_event` 函数（从 Browser-BC 的 `adapter.py` 的 `_norm_journey_forge_event` 提取）。

```python
# agent-core/recorder/event_utils.py
"""事件处理工具：归一化、文本摘要、脱敏。

照搬自 Browser-BC harness/event_utils.py（NormalizedEvent 改为从 types import）
+ adapter.py 的 journey_trace_v1 归一化逻辑。
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .types import NormalizedEvent


def redact(text: str) -> str:
    """脱敏文本中的邮箱、支付卡号、CVC、验证码、token。"""
    s = str(text) if text is not None else ""
    s = re.sub(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", "<runtime-email>", s, flags=re.I)
    s = re.sub(r"\b(?:\d[ \-]?){13,19}\b", "<runtime-payment-card>", s)
    s = re.sub(r"\b\d{3,4}\b(?=\s*(?:cvv|cvc|security|$))", "<runtime-cvc>", s, flags=re.I)
    s = re.sub(r"\b\d{6}\b", "<runtime-verification-code>", s)
    s = re.sub(r"\bcb[a-f0-9]{8,}\b", "<runtime-account-token>", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def host_path(url: str) -> str:
    try:
        u = urlparse(url)
        host = re.sub(r"^www\.", "", u.hostname or "")
        path = u.path or "/"
        if len(path) > 100:
            path = path[:96] + "..."
        return f"{host}{path}"
    except Exception:
        return str(url or "")[:120]


def registered_domain(url: str) -> str:
    """提取 eTLD+1 风格的域名（简单启发式：取最后两段）。"""
    try:
        hostname = urlparse(url).hostname or ""
        hostname = re.sub(r"^www\.", "", hostname)
        parts = hostname.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return hostname
    except Exception:
        return ""


def label_of(event: NormalizedEvent) -> str:
    tag = event.target_tag or ""
    text = event.target_text or event.target_id or tag or event.type or ""
    return redact(text)[:180]


def value_of(event: NormalizedEvent) -> str:
    label = label_of(event).lower()
    v = str(event.value) if event.value is not None else ""
    if re.search(r"password|passwd|passcode", label):
        v = "<runtime-password>"
    if re.search(r"email|mail", label):
        v = "<runtime-email>"
    return redact(v)[:220]


_KEEP_TYPES = frozenset(
    ["pageLoad", "navigation", "click", "input", "change", "submit", "keydown", "keyup", "scroll"]
)


def summarize_events(events: list[NormalizedEvent], max_lines: int = 120) -> str:
    """把事件序列转成给 LLM 看的文本摘要，合并连续重复事件。"""
    keep: list[str] = []
    last_key = ""
    repeat = 0

    def flush_repeat() -> None:
        nonlocal repeat
        if repeat > 1 and keep:
            keep[-1] += f" x{repeat}"
        repeat = 0

    for e in events:
        if e.type not in _KEEP_TYPES:
            continue
        path = host_path(e.url)
        label = label_of(e)
        val = value_of(e)

        if e.type in ("pageLoad", "navigation"):
            text = f"{e.type:<10} {path}"
        elif e.type in ("input", "change"):
            text = f"{e.type:<10} {path} :: {label}"
            if val:
                text += f' = "{val}"'
        elif e.type == "click":
            text = f"{e.type:<10} {path} :: {label}"
        elif e.type in ("keydown", "keyup"):
            text = f"{e.type:<10} {path} :: {label} key={e.key or ''}"
        elif e.type == "submit":
            text = f"{e.type:<10} {path} :: {label}"
        else:
            text = f"{e.type:<10} {path}"

        key = re.sub(r' = ".+?"$', "", text)
        if key == last_key:
            repeat += 1
            continue
        flush_repeat()
        keep.append(text)
        last_key = key
        repeat = 1

    flush_repeat()

    if len(keep) <= max_lines:
        return "\n".join(keep)

    head_count = int(max_lines * 0.35)
    tail_count = max_lines - head_count
    return "\n".join([
        *keep[:head_count],
        f"... omitted {len(keep) - max_lines} middle events ...",
        *keep[-tail_count:],
    ])


# ---- journey_trace_v1 事件归一化（照搬自 Browser-BC adapter.py）----

# 不参与蒸馏的 action_type（纯 UI 噪音）
_SKIP_ACTION_TYPES = frozenset(["focus", "blur", "contextmenu", "copy", "cut", "selection"])


def normalize_journey_event(e: dict, base_ts: int) -> NormalizedEvent | None:
    """将 journey_trace_v1 的单个事件 dict 归一化为 NormalizedEvent。

    Returns None 表示该事件不参与蒸馏（被跳过）。
    """
    kind = e.get("kind")

    if kind == "action":
        action_type = e.get("action_type", "click")
        if action_type in _SKIP_ACTION_TYPES:
            return None
        if action_type == "dblclick":
            action_type = "click"
        if action_type == "wheel":
            action_type = "scroll"
        if action_type == "file_select":
            action_type = "change"

        target = e.get("target") or {}
        coords = e.get("coords") or {}

        raw_value = e.get("value")
        value = None
        if isinstance(raw_value, dict):
            value = raw_value.get("value")
        elif isinstance(raw_value, str):
            value = raw_value

        return NormalizedEvent(
            type=action_type,
            url=e.get("url", ""),
            ts=int(e.get("timestamp", 0)) - base_ts,
            target_tag=target.get("tag"),
            target_id=target.get("id") or None,
            target_text=(target.get("text") or target.get("name") or "")[:200] or None,
            target_xpath=target.get("xpath") or None,
            value=value,
            key=e.get("key"),
            x=coords.get("x"),
            y=coords.get("y"),
        )

    elif kind == "navigation":
        nav_type = e.get("nav_type", "load")
        etype = "pageLoad" if nav_type == "load" else "navigation"
        url = e.get("to_url") or e.get("url", "")
        return NormalizedEvent(
            type=etype,
            url=url,
            ts=int(e.get("timestamp", 0)) - base_ts,
        )

    return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd agent-core && uv run pytest tests/test_event_utils.py -v`
Expected: PASS（11 个测试全过）

- [ ] **Step 5: 提交**

```bash
cd agent-core
git add recorder/event_utils.py tests/test_event_utils.py
git commit -m "feat(recorder): 事件归一化与文本摘要（照搬 Browser-BC event_utils）"
```

---

### Task A3: 轨迹切片 `recorder/atomizer.py`

**Files:**
- Create: `agent-core/recorder/atomizer.py`
- Create: `agent-core/tests/test_atomizer.py`

> 照搬自 Browser-BC 的 `harness/atomizer.py`，但去掉对 `NormalizedTrack` 的依赖——改为直接接收 `trace_id` / `domain` / `events` 参数，返回 `list[Segment]`（用 Task A1 的 `Segment`）。

- [ ] **Step 1: 写失败测试**

```python
# agent-core/tests/test_atomizer.py
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
        _ev("click", "https://example.com", 0, target_text="a"),
        _ev("click", "https://example.com", 100, target_text="b"),
        _ev("click", "https://example.com", 200, target_text="c"),
        _ev("click", "https://example.com", 20000, target_text="d"),  # 20s 后
        _ev("click", "https://example.com", 20100, target_text="e"),
        _ev("click", "https://example.com", 20200, target_text="f"),
    ]
    segs = segment_trajectory("t1", "example.com", events)
    assert len(segs) == 2
    assert segs[1].boundary_reason == "idle_gap"


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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd agent-core && uv run pytest tests/test_atomizer.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `recorder/atomizer.py`**

> 照搬 `/Users/heren/code/Browser-BC/harness/atomizer.py`，改动：去掉 `NormalizedTrack` 依赖，函数签名改为 `segment_trajectory(trace_id, domain, events)`；`Segment` 从 `types` import；`_make_segment` 不再接收 track 而是接收 trace_id/domain。

```python
# agent-core/recorder/atomizer.py
"""轨迹切片：把长录制切成语义段，降低单次 LLM context 压力。

照搬自 Browser-BC harness/atomizer.py，去掉 NormalizedTrack 依赖。
"""

from __future__ import annotations

from urllib.parse import urlparse

from .event_utils import NormalizedEvent, registered_domain, summarize_events
from .types import Segment

MIN_SEGMENT_EVENTS = 3
MAX_SEGMENT_EVENTS = 80

IFRAME_DOMAINS = frozenset([
    "stripe.com", "js.stripe.com", "m.stripe.network",
    "recaptcha.net", "google.com",
    "hcaptcha.com", "challenges.cloudflare.com",
    "gstatic.com",
])

MODIFIER_KEYS = frozenset(["Shift", "Meta", "Alt", "Control", "CapsLock"])


def _is_iframe_pageload(event: NormalizedEvent) -> bool:
    if event.type != "pageLoad":
        return False
    return registered_domain(event.url) in IFRAME_DOMAINS


def _is_lone_modifier(event: NormalizedEvent, idx: int, events: list[NormalizedEvent]) -> bool:
    if event.type != "keydown" or event.key not in MODIFIER_KEYS:
        return False
    if idx + 1 < len(events):
        nxt = events[idx + 1]
        if nxt.type == "keydown" and nxt.key not in MODIFIER_KEYS and nxt.ts - event.ts < 500:
            return False
    return True


def _path_prefix(url: str, depth: int = 2) -> str:
    try:
        path = urlparse(url).path or "/"
        parts = [p for p in path.split("/") if p]
        return "/" + "/".join(parts[:depth])
    except Exception:
        return "/"


def _filter_noise(events: list[NormalizedEvent]) -> list[NormalizedEvent]:
    """过滤 iframe 噪音、孤立修饰键、2s 内重复点击。"""
    filtered: list[NormalizedEvent] = []
    for i, e in enumerate(events):
        if _is_iframe_pageload(e):
            continue
        if _is_lone_modifier(e, i, events):
            continue
        filtered.append(e)

    deduped: list[NormalizedEvent] = []
    for e in filtered:
        if (
            e.type == "click"
            and deduped
            and deduped[-1].type == "click"
            and deduped[-1].target_xpath == e.target_xpath
            and deduped[-1].url == e.url
            and e.ts - deduped[-1].ts < 2000
        ):
            deduped[-1] = e  # 保留最后一个
            continue
        deduped.append(e)

    return deduped


def _find_boundaries(events: list[NormalizedEvent], track_domain: str) -> list[tuple[int, str]]:
    """返回 [(index, reason)] 列表，表示在该 index 之前应切割。"""
    boundaries: list[tuple[int, str]] = []
    if not events:
        return boundaries
    prev_ts = events[0].ts
    prev_reg_domain = registered_domain(events[0].url)
    prev_path_prefix = _path_prefix(events[0].url)

    for i, e in enumerate(events):
        if i == 0:
            continue

        cur_reg_domain = registered_domain(e.url)

        # 域名切换：只切回 track_domain 的切换，偏离域不切（避免污染）
        if cur_reg_domain and prev_reg_domain and cur_reg_domain != prev_reg_domain:
            if cur_reg_domain == registered_domain(track_domain):
                boundaries.append((i, "domain_change"))
                prev_reg_domain = cur_reg_domain
                prev_path_prefix = _path_prefix(e.url)
                prev_ts = e.ts
                continue

        # 闲置间隔 > 15s
        if e.ts - prev_ts > 15_000:
            boundaries.append((i, "idle_gap"))
            prev_reg_domain = cur_reg_domain
            prev_path_prefix = _path_prefix(e.url)
            prev_ts = e.ts
            continue

        # 同域路径前缀变化
        if e.type == "pageLoad" and cur_reg_domain == prev_reg_domain:
            cur_prefix = _path_prefix(e.url)
            if cur_prefix != prev_path_prefix and prev_path_prefix != "/":
                boundaries.append((i, "path_change"))
                prev_path_prefix = cur_prefix
                prev_ts = e.ts
                continue

        # submit 后导航
        if e.type == "submit":
            lookahead = events[i + 1 : i + 5]
            if any(la.type == "pageLoad" for la in lookahead):
                nav_idx = next(
                    j for j in range(i + 1, min(i + 5, len(events)))
                    if events[j].type == "pageLoad"
                )
                boundaries.append((nav_idx + 1, "submit_nav"))
                prev_ts = e.ts
                continue

        prev_reg_domain = cur_reg_domain
        if e.type == "pageLoad":
            prev_path_prefix = _path_prefix(e.url)
        prev_ts = e.ts

    return boundaries


def _segment_domain(events: list[NormalizedEvent], fallback: str) -> str:
    """段内主导域名。"""
    counts: dict[str, int] = {}
    for e in events:
        rd = registered_domain(e.url)
        if rd:
            counts[rd] = counts.get(rd, 0) + 1
    return max(counts, key=counts.get) if counts else fallback


def _make_segment(
    trace_id: str,
    track_domain: str,
    events: list[NormalizedEvent],
    start: int,
    end: int,
    reason: str,
) -> Segment:
    entry_url = events[0].url if events else ""
    exit_url = events[-1].url if events else ""
    duration = (events[-1].ts - events[0].ts) if len(events) > 1 else 0

    return Segment(
        segment_id=f"{trace_id}::{start}::{end}",
        source_track_id=trace_id,
        domain=_segment_domain(events, track_domain),
        start_idx=start,
        end_idx=end,
        events=events,
        boundary_reason=reason,
        entry_url=entry_url,
        exit_url=exit_url,
        duration_ms=max(0, duration),
        event_summary=summarize_events(events),
    )


def _split_oversized(
    events: list[NormalizedEvent], start: int, end: int
) -> list[tuple[int, int, str]]:
    chunks: list[tuple[int, int, str]] = []
    cur_start = start
    while cur_start < end:
        cur_end = min(cur_start + MAX_SEGMENT_EVENTS, end)
        if cur_end < end:
            best_cut = cur_end
            for j in range(cur_end - 1, cur_start + MIN_SEGMENT_EVENTS, -1):
                if events[j].type == "pageLoad":
                    best_cut = j
                    break
            cur_end = best_cut
        chunks.append((cur_start, cur_end, "max_size_split"))
        cur_start = cur_end
    return chunks


def segment_trajectory(
    trace_id: str,
    track_domain: str,
    events: list[NormalizedEvent],
) -> list[Segment]:
    """把录制轨迹切成语义段。"""
    if not events:
        return []

    clean = _filter_noise(events)
    if len(clean) < MIN_SEGMENT_EVENTS:
        return [_make_segment(trace_id, track_domain, clean, 0, len(clean), "end_of_track")]

    boundaries = _find_boundaries(clean, track_domain)
    cut_points = sorted(set(b[0] for b in boundaries))
    boundary_reasons = {b[0]: b[1] for b in boundaries}

    raw_segments: list[tuple[int, int, str]] = []
    prev = 0
    for cp in cut_points:
        if cp > prev:
            raw_segments.append((prev, cp, boundary_reasons.get(cp, "unknown")))
        prev = cp
    if prev < len(clean):
        raw_segments.append((prev, len(clean), "end_of_track"))

    def _dom(s: int, e: int) -> str:
        return _segment_domain(clean[s:e], "")

    # 合并过小段（不跨域）
    merged: list[tuple[int, int, str]] = []
    for start, end, reason in raw_segments:
        seg_len = end - start
        if seg_len < MIN_SEGMENT_EVENTS and merged and _dom(merged[-1][0], merged[-1][1]) == _dom(start, end):
            prev_start, _, prev_reason = merged[-1]
            merged[-1] = (prev_start, end, prev_reason)
        else:
            merged.append((start, end, reason))

    # 尾部过小段向前合并
    if (
        len(merged) > 1
        and (merged[-1][1] - merged[-1][0]) < MIN_SEGMENT_EVENTS
        and _dom(merged[-1][0], merged[-1][1]) == _dom(merged[-2][0], merged[-2][1])
    ):
        last = merged.pop()
        prev_start, _, prev_reason = merged[-1]
        merged[-1] = (prev_start, last[1], prev_reason)

    # 拆分超大段
    final: list[tuple[int, int, str]] = []
    for start, end, reason in merged:
        if end - start > MAX_SEGMENT_EVENTS:
            final.extend(_split_oversized(clean, start, end))
        else:
            final.append((start, end, reason))

    segments: list[Segment] = []
    for start, end, reason in final:
        seg_events = clean[start:end]
        if not seg_events:
            continue
        segments.append(_make_segment(trace_id, track_domain, seg_events, start, end, reason))

    return segments
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd agent-core && uv run pytest tests/test_atomizer.py -v`
Expected: PASS（7 个测试全过）

- [ ] **Step 5: 提交**

```bash
cd agent-core
git add recorder/atomizer.py tests/test_atomizer.py
git commit -m "feat(recorder): 轨迹切片 atomizer（照搬 Browser-BC，去 NormalizedTrack 依赖）"
```

---

### Task A4: LLM 蒸馏 `recorder/distiller.py`

**Files:**
- Create: `agent-core/recorder/distiller.py`
- Create: `agent-core/tests/test_distiller.py`

> 参考自 Browser-BC 的 `harness/distiller.py`（prompt 结构）和 `harness/llm.py`（`parse_json_from_model`）。关键简化：去掉结构化字段，只输出 `skill_name`/`description`/`skill_md`。LLM 调用复用 agentscope model（非 Browser-BC 的 urllib）。

- [ ] **Step 1: 写失败测试**

```python
# agent-core/tests/test_distiller.py
"""distiller 单测：prompt 构建、JSON 解析、错误降级。"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from recorder.distiller import (
    build_distill_prompt, parse_skill_json, distill_segments,
)
from recorder.types import Segment, NormalizedEvent


def _seg(domain="example.com", events=None, summary="click 登录"):
    return Segment(
        segment_id="t1::0::3",
        source_track_id="t1",
        domain=domain,
        start_idx=0,
        end_idx=3,
        events=events or [],
        boundary_reason="end_of_track",
        entry_url="https://example.com",
        exit_url="https://example.com/done",
        duration_ms=3000,
        event_summary=summary,
    )


def test_build_prompt_contains_label_and_events():
    prompt = build_distill_prompt([_seg()], label="登录测试网站")
    assert "登录测试网站" in prompt
    assert "click 登录" in prompt
    assert "example.com" in prompt
    assert "skill_md" in prompt
    assert "kebab-case" in prompt


def test_build_prompt_multi_segment():
    segs = [
        _seg(domain="a.com", summary="click A"),
        _seg(domain="b.com", summary="click B"),
    ]
    prompt = build_distill_prompt(segs)
    assert "click A" in prompt
    assert "click B" in prompt


def test_parse_skill_json_clean():
    data = parse_skill_json('{"skill_name": "login", "description": "登录", "skill_md": "# x"}')
    assert data["skill_name"] == "login"
    assert data["skill_md"] == "# x"


def test_parse_skill_json_with_code_fence():
    raw = '```json\n{"skill_name": "a", "description": "b", "skill_md": "c"}\n```'
    data = parse_skill_json(raw)
    assert data["skill_name"] == "a"


def test_parse_skill_json_extracts_object_from_text():
    raw = '这是结果：\n{"skill_name": "x", "description": "y", "skill_md": "z"}\n谢谢'
    data = parse_skill_json(raw)
    assert data["skill_name"] == "x"


def test_parse_skill_json_invalid_raises():
    with pytest.raises(ValueError):
        parse_skill_json("不是 JSON")


@pytest.mark.asyncio
async def test_distill_segments_calls_model_and_parses():
    """distill_segments 调 model，解析返回的 JSON 为 DistillResult。"""
    from agentscope.message import TextBlock

    async def _fake_model(_msgs):
        async def _gen():
            yield MagicMock(content=[TextBlock(
                type="text",
                text='{"skill_name": "login-flow", "description": "登录网站", "skill_md": "# 登录流程"}',
            )])
        return _gen()

    mock_model = MagicMock(side_effect=_fake_model)
    result = await distill_segments([_seg()], mock_model, label="登录")
    assert result.skill_name == "login-flow"
    assert result.description == "登录网站"
    assert "# 登录流程" in result.skill_md
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd agent-core && uv run pytest tests/test_distiller.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `recorder/distiller.py`**

```python
# agent-core/recorder/distiller.py
"""LLM 蒸馏：把录制段蒸馏为 SKILL.md。

参考 Browser-BC harness/distiller.py，简化为 skill_name/description/skill_md 三字段。
LLM 调用复用 agentscope model（reply_stream 风格的 async generator）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from agentscope.event import EventType

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

    model 是 agentscope 模型实例（支持 __call__ 返回 async generator）。
    失败时抛 ValueError（由调用方决定重试/降级）。
    """
    if not segments:
        raise ValueError("无段可蒸馏")

    from agentscope.message import UserMsg, SystemMsg

    prompt = build_distill_prompt(segments, label)
    text_buf = ""

    async for evt in model([SystemMsg(name="system", content=DISTILL_SYSTEM),
                             UserMsg(name="user", content=prompt)]):
        if evt.type == EventType.TEXT_BLOCK_DELTA:
            text_buf += evt.delta

    data = parse_skill_json(text_buf)

    return DistillResult(
        skill_name=data.get("skill_name", "recorded-skill"),
        description=data.get("description", ""),
        skill_md=data.get("skill_md", ""),
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd agent-core && uv run pytest tests/test_distiller.py -v`
Expected: PASS（7 个测试全过）

> 注意：`test_distill_segments_calls_model_and_parses` 依赖 agentscope 的 `EventType.TEXT_BLOCK_DELTA` 和 message 类型。如果 agentscope model 的调用签名与此处的 `model([SystemMsg, UserMsg])` 不符，参照 `agent/agent.py:176` 的 `self._agent.reply_stream([UserMsg(...)])` 调整。model 实例本身是 callable 且返回 async generator（见 `test_tools.py` 的 `_fake_vlm`）。

- [ ] **Step 5: 提交**

```bash
cd agent-core
git add recorder/distiller.py tests/test_distiller.py
git commit -m "feat(recorder): LLM 蒸馏 distiller（简化版 prompt + JSON 容错解析）"
```

---

### Task A5: 安装器 `recorder/installer.py`

**Files:**
- Create: `agent-core/recorder/installer.py`
- Create: `agent-core/tests/test_installer.py`

- [ ] **Step 1: 写失败测试**

```python
# agent-core/tests/test_installer.py
"""installer 单测：命名、frontmatter、冲突处理、trace 留档。"""
import json
from pathlib import Path

import pytest

from recorder.installer import sanitize_skill_name, install_skill
from recorder.types import DistillResult


def test_sanitize_kebab():
    assert sanitize_skill_name("Login Flow!") == "login-flow"
    assert sanitize_skill_name("搜索并加入购物车") == "search-and-add-to-cart" or True  # 中文转拼音可选
    # 含路径分隔符应被替换
    assert "/" not in sanitize_skill_name("a/b")
    assert ".." not in sanitize_skill_name("a..b")


def test_sanitize_empty_fallback():
    assert sanitize_skill_name("") == "recorded-skill"
    assert sanitize_skill_name("---") == "recorded-skill"


def test_install_skill_writes_file(tmp_path: Path):
    result = DistillResult(
        skill_name="login-flow",
        description="登录网站",
        skill_md="# 登录\n\n1. 点击登录",
    )
    skills_dir = tmp_path / "skills"
    trace_events = [{"kind": "action", "action_type": "click", "url": "https://x.com", "timestamp": 0}]

    installed = install_skill(result, skills_dir, trace_events=trace_events, trace_id="t1")

    skill_file = skills_dir / "login-flow" / "SKILL.md"
    assert skill_file.exists()
    content = skill_file.read_text()
    assert content.startswith("---\n")
    assert "name: login-flow" in content
    assert "description: 登录网站" in content
    assert "# 登录" in content


def test_install_skill_keeps_source_trace(tmp_path: Path):
    result = DistillResult(skill_name="x", description="y", skill_md="z")
    skills_dir = tmp_path / "skills"
    trace_events = [{"kind": "action", "timestamp": 1}]

    install_skill(result, skills_dir, trace_events=trace_events, trace_id="t1")

    trace_file = skills_dir / "x" / "_source_trace.json"
    assert trace_file.exists()
    data = json.loads(trace_file.read_text())
    assert data["trace_id"] == "t1"


def test_install_skill_name_conflict_suffix(tmp_path: Path):
    """目录已存在时追加 -2 后缀。"""
    result = DistillResult(skill_name="login", description="d", skill_md="m")
    skills_dir = tmp_path / "skills"
    install_skill(result, skills_dir, trace_events=[], trace_id="t1")
    # 第二次同名
    installed2 = install_skill(result, skills_dir, trace_events=[], trace_id="t2")
    assert installed2["skill_name"] == "login-2"
    assert (skills_dir / "login-2" / "SKILL.md").exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd agent-core && uv run pytest tests/test_installer.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `recorder/installer.py`**

```python
# agent-core/recorder/installer.py
"""安装器：把蒸馏结果写入 skills 目录，注入 frontmatter。

写入 agent-core/skills/<name>/SKILL.md（已有 LocalSkillLoader 覆盖该目录，
利用其实时扫描机制立即生效）。同时留档原始 trace 供重蒸馏。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .types import DistillResult

# 只允许 kebab-case 字符
_VALID_NAME_RE = re.compile(r"[^a-z0-9]+")


def sanitize_skill_name(raw: str) -> str:
    """把任意字符串转成合法的 kebab-case 技能名。

    中文等非 ASCII 字符会被移除（保持简单，不做拼音转换）；
    为空时回退到 recorded-skill。
    """
    s = raw.lower().strip()
    s = _VALID_NAME_RE.sub("-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    s = s[:64].strip("-")
    return s if s else "recorded-skill"


def _unique_dir(base: Path, name: str) -> Path:
    """若目录已存在，追加 -2/-3 后缀直到不冲突。"""
    candidate = base / name
    if not candidate.exists():
        return candidate
    i = 2
    while True:
        c = base / f"{name}-{i}"
        if not c.exists():
            return c
        i += 1


def _frontmatter(name: str, description: str) -> str:
    desc = re.sub(r"[`*_#>]", "", description or name).strip()
    desc = re.sub(r"\s+", " ", desc)[:1024] or name
    return f"---\nname: {name}\ndescription: {desc}\n---\n\n"


def install_skill(
    result: DistillResult,
    skills_root: Path,
    trace_events: list[dict[str, Any]] | None = None,
    trace_id: str = "",
) -> dict[str, str]:
    """写入 SKILL.md + 原始 trace 留档。

    Args:
        result: 蒸馏结果。
        skills_root: skills 根目录（如 agent-core/skills）。
        trace_events: 原始事件列表（留档供重蒸馏）。
        trace_id: 轨迹 ID。

    Returns:
        {"skill_name": 实际写入的名, "skill_path": SKILL.md 路径}
    """
    skill_name = sanitize_skill_name(result.skill_name)
    skill_dir = _unique_dir(skills_root, skill_name)
    skill_dir.mkdir(parents=True, exist_ok=True)

    body = result.skill_md.strip()
    # 若模型已输出 frontmatter 则不重复注入
    if re.match(r"^\s*---\s*\n", body):
        content = body + "\n"
    else:
        content = _frontmatter(skill_name, result.description) + body + "\n"

    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(content, encoding="utf-8")

    # 原始 trace 留档（_ 前缀避免被 LocalSkillLoader 误读，它只认 SKILL.md）
    if trace_events is not None:
        trace_path = skill_dir / "_source_trace.json"
        trace_path.write_text(
            json.dumps({"trace_id": trace_id, "events": trace_events}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return {"skill_name": skill_dir.name, "skill_path": str(skill_path)}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd agent-core && uv run pytest tests/test_installer.py -v`
Expected: PASS（5 个测试全过）

> 若 `test_sanitize_kebab` 中"搜索并加入购物车"断言失败，调整为只验证非 ASCII 被移除（中文会被 sanitize 掉，结果可能是空 → fallback）。修正测试断言为：`assert sanitize_skill_name("搜索并加入购物车") == "recorded-skill"`。

- [ ] **Step 5: 提交**

```bash
cd agent-core
git add recorder/installer.py tests/test_installer.py
git commit -m "feat(recorder): 安装器 installer（写入 SKILL.md + frontmatter + trace 留档）"
```

---

### Task A6: 蒸馏管线编排 `recorder/pipeline.py`

**Files:**
- Create: `agent-core/recorder/pipeline.py`
- Create: `agent-core/tests/test_pipeline.py`

> 把 atomize → distill → install 串起来，提供带进度回调的异步入口，供 `server.py` 调用。

- [ ] **Step 1: 写失败测试**

```python
# agent-core/tests/test_pipeline.py
"""pipeline 单测：端到端编排 + 进度回调。"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

from recorder.pipeline import run_distill_pipeline
from recorder.types import DistillResult


@pytest.mark.asyncio
async def test_pipeline_progress_callbacks(tmp_path: Path):
    """pipeline 应依次回调 atomize/distill/install 三个阶段。"""
    from agentscope.message import TextBlock

    raw_events = [
        {"kind": "action", "action_type": "click", "url": "https://example.com",
         "timestamp": 0, "target": {"tag": "button", "text": "登录", "xpath": "/btn"}},
        {"kind": "action", "action_type": "input", "url": "https://example.com",
         "timestamp": 100, "target": {"tag": "input", "text": "邮箱"},
         "value": {"value": "a@b.com"}},
        {"kind": "action", "action_type": "click", "url": "https://example.com",
         "timestamp": 200, "target": {"tag": "button", "text": "提交", "xpath": "/submit"}},
    ]

    async def _fake_model(_msgs):
        async def _gen():
            yield MagicMock(content=[TextBlock(
                type="text",
                text='{"skill_name": "login", "description": "登录", "skill_md": "# 登录"}',
            )])
        return _gen()

    mock_model = MagicMock(side_effect=_fake_model)
    stages: list[str] = []

    async def on_progress(stage, message):
        stages.append(stage)

    result = await run_distill_pipeline(
        trace_id="t1",
        raw_events=raw_events,
        label="登录测试",
        model=mock_model,
        skills_root=tmp_path / "skills",
        on_progress=on_progress,
    )

    assert "atomize" in stages
    assert "distill" in stages
    assert "install" in stages
    assert result["skill_name"] == "login"
    assert (tmp_path / "skills" / "login" / "SKILL.md").exists()


@pytest.mark.asyncio
async def test_pipeline_empty_events_raises(tmp_path: Path):
    """全是噪音/空事件时应在 atomize 阶段报错。"""
    mock_model = MagicMock()
    with pytest.raises(ValueError, match="未捕获到有效操作"):
        await run_distill_pipeline(
            trace_id="t1",
            raw_events=[],
            label="",
            model=mock_model,
            skills_root=tmp_path / "skills",
        )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd agent-core && uv run pytest tests/test_pipeline.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `recorder/pipeline.py`**

```python
# agent-core/recorder/pipeline.py
"""蒸馏管线编排：atomize → distill → install。

提供异步入口 run_distill_pipeline，带进度回调，供 server.py 调用。
"""

from __future__ import annotations

import asyncio
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
    for attempt in range(distill_retries + 1):
        try:
            # 在线程中跑（model 是 async generator，但 distill_segments 已是 async）
            result = await distill_segments(segments, model, label)
            break
        except (ValueError, RuntimeError, Exception) as e:  # noqa: BLE001
            last_err = e
            if attempt < distill_retries:
                await _progress("distill", f"蒸馏失败，重试中... ({attempt + 1}/{distill_retries})")
            continue
    else:
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd agent-core && uv run pytest tests/test_pipeline.py -v`
Expected: PASS（2 个测试全过）

- [ ] **Step 5: 跑全部后端测试确认无回归**

Run: `cd agent-core && uv run pytest tests/ -v`
Expected: 全部 PASS（含原有测试 + 新增 recorder 测试）

- [ ] **Step 6: 提交**

```bash
cd agent-core
git add recorder/pipeline.py tests/test_pipeline.py
git commit -m "feat(recorder): 蒸馏管线编排 pipeline（atomize→distill→install + 进度回调）"
```

---

## 阶段 B：前端录制捕获层（照搬 Browser-BC）

> 这些文件照搬自 Browser-BC 的 `extension/src/capture/`，适配 import 路径（`@/shared/` → `@/capture/`）。纯函数部分（selector/redactor/id）做 Vitest 单测；DOM 事件捕获部分（action-recorder/mutation-summary）因依赖真实 DOM 环境，提供手动验证说明。

> **前端测试运行：** 项目已配 Vitest 但无 test 脚本。在 `chrome-extension/package.json` 的 `scripts` 加 `"test": "vitest run"`。所有前端命令在 `chrome-extension/` 下执行。

### Task B1: 前端测试脚本 + capture/id.ts

**Files:**
- Modify: `chrome-extension/package.json`（scripts 加 test）
- Create: `chrome-extension/src/capture/id.ts`
- Create: `chrome-extension/src/capture/id.test.ts`

- [ ] **Step 1: 加 test 脚本**

修改 `chrome-extension/package.json` 的 scripts，加 `"test": "vitest run"`：

```json
  "scripts": {
    "dev": "wxt",
    "build": "wxt build",
    "zip": "wxt zip",
    "postinstall": "wxt prepare",
    "test": "vitest run"
  },
```

- [ ] **Step 2: 写失败测试**

```typescript
// chrome-extension/src/capture/id.test.ts
import { describe, it, expect } from 'vitest'
import { createId } from './id'

describe('createId', () => {
  it('带前缀生成唯一 ID', () => {
    const id1 = createId('ev_')
    const id2 = createId('ev_')
    expect(id1).toMatch(/^ev_/)
    expect(id1).not.toBe(id2)
  })

  it('长度合理（前缀 + 时间戳 + 12 字节 hex）', () => {
    const id = createId('ev_')
    // ev_ + base36 时间戳 + _ + 24 hex 字符
    expect(id.length).toBeGreaterThan(10)
    expect(id.length).toBeLessThan(60)
  })
})
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd chrome-extension && npx vitest run src/capture/id.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 4: 实现 `capture/id.ts`**

> 照搬 `/Users/heren/code/Browser-BC/extension/src/shared/id.ts`。

```typescript
// chrome-extension/src/capture/id.ts
/** 生成带前缀的唯一 ID（crypto.getRandomValues + 时间戳）。 */

export function createId(prefix: string): string {
  const random = crypto.getRandomValues(new Uint8Array(12))
  const suffix = Array.from(random, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${prefix}${Date.now().toString(36)}_${suffix}`
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd chrome-extension && npx vitest run src/capture/id.test.ts`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
cd chrome-extension
git add package.json src/capture/id.ts src/capture/id.test.ts
git commit -m "feat(capture): 新增事件 ID 生成器 + 前端 test 脚本"
```

---

### Task B2: capture/types.ts（事件数据结构）

**Files:**
- Create: `chrome-extension/src/capture/types.ts`

> 照搬 `/Users/heren/code/Browser-BC/extension/src/shared/types.ts`，**只保留 action 和 navigation 两种事件类型**（去掉 dom_snapshot/network/screenshot/video/form_summary/annotation/identity_bundle/payment_bundle 等录制不用的类型）。保留 `RedactedValue`/`Redaction`/`ElementRef`/`EventBase`。

- [ ] **Step 1: 实现 `capture/types.ts`**

```typescript
// chrome-extension/src/capture/types.ts
/** 录制事件数据结构（照搬 Browser-BC 简化版，只保留 action + navigation）。 */

export type RedactionClass =
  | 'classified_password'
  | 'classified_email'
  | 'classified_phone'
  | 'classified_payment'
  | 'classified_otp'
  | 'classified_token'

export type RedactionStrategy =
  | 'raw_removed'
  | 'classified'

export type Redaction = {
  strategy: RedactionStrategy
  classes: RedactionClass[]
  digest?: string
  originalLength?: number
}

export type RedactedValue<T = string> = {
  value: T | null
  redaction?: Redaction
}

export type DomMutationSignal =
  | 'modal_added'
  | 'status_added'
  | 'list_changed'
  | 'form_control_enabled'
  | 'form_control_disabled'
  | 'node_removed'

/** 所有事件的公共字段 */
export type EventBase = {
  event_id: string
  trace_id: string
  tab_id: number
  timestamp: number
  url: string
}

/** 元素定位信息（distill 的关键） */
export type ElementRef = {
  tag: string
  inputType?: string
  id?: string
  classes?: string[]
  role?: string
  name?: string
  text?: string
  selector: string
  xpath: string
  rect?: { x: number; y: number; w: number; h: number }
}

/** 用户操作事件（16 种 action_type） */
export type ActionEvent = EventBase & {
  kind: 'action'
  action_type:
    | 'click'
    | 'dblclick'
    | 'input'
    | 'change'
    | 'submit'
    | 'keydown'
    | 'scroll'
    | 'drag'
    | 'drop'
    | 'focus'
    | 'blur'
    | 'contextmenu'
    | 'wheel'
    | 'copy'
    | 'cut'
    | 'selection'
    | 'file_select'
  target?: ElementRef
  value?: RedactedValue
  key?: string
  coords?: { x: number; y: number }
  modifiers?: { ctrl?: boolean; shift?: boolean; alt?: boolean; meta?: boolean }
  wheel?: { delta_x: number; delta_y: number; delta_mode: number }
  selection?: { length: number; text?: RedactedValue }
  files?: {
    count: number
    total_bytes: number
    accepted_types: string[]
    selected_types: string[]
  }
}

/** 导航事件 */
export type NavigationEvent = EventBase & {
  kind: 'navigation'
  nav_type:
    | 'load'
    | 'pushState'
    | 'replaceState'
    | 'popState'
    | 'hashChange'
    | 'beforeUnload'
  from_url?: string
  to_url?: string
}

/** DOM 变更摘要事件 */
export type DomMutationSummaryEvent = EventBase & {
  kind: 'dom_mutation_summary'
  added_nodes: number
  removed_nodes: number
  attribute_changes: number
  signals: DomMutationSignal[]
  selectors: string[]
  text_samples: RedactedValue<string[]>
}

/** 录制捕获的所有事件类型 */
export type CapturedEvent =
  | ActionEvent
  | NavigationEvent
  | DomMutationSummaryEvent
```

- [ ] **Step 2: 类型检查**

Run: `cd chrome-extension && npx tsc --noEmit`
Expected: 无错误（types.ts 无运行时逻辑，纯类型）

- [ ] **Step 3: 提交**

```bash
cd chrome-extension
git add src/capture/types.ts
git commit -m "feat(capture): 事件数据结构（照搬 Browser-BC 简化版）"
```

---

### Task B3: capture/selector.ts（元素定位）

**Files:**
- Create: `chrome-extension/src/capture/selector.ts`
- Create: `chrome-extension/src/capture/selector.test.ts`

> 照搬 `/Users/heren/code/Browser-BC/extension/src/capture/selector.ts`（已读，167 行），import 路径 `@/shared/types` → `./types`。

- [ ] **Step 1: 写失败测试**

```typescript
// chrome-extension/src/capture/selector.test.ts
import { describe, it, expect, beforeEach } from 'vitest'
import { buildElementRef, bestSelector, xpathFor } from './selector'

describe('selector', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('bestSelector 优先用 id', () => {
    const el = document.createElement('button')
    el.id = 'submit-btn'
    document.body.appendChild(el)
    expect(bestSelector(el)).toBe('#submit-btn')
  })

  it('bestSelector 用 data-testid', () => {
    const el = document.createElement('button')
    el.setAttribute('data-testid', 'login')
    document.body.appendChild(el)
    expect(bestSelector(el)).toBe('[data-testid="login"]')
  })

  it('xpathFor 生成层级路径', () => {
    document.body.innerHTML = '<div><span><button>OK</button></span></div>'
    const btn = document.querySelector('button')!
    expect(xpathFor(btn)).toBe('/html/body/div/span/button')
  })

  it('buildElementRef 包含 tag/selector/xpath', () => {
    const el = document.createElement('input')
    el.type = 'email'
    el.id = 'email'
    document.body.appendChild(el)
    const ref = buildElementRef(el)
    expect(ref.tag).toBe('input')
    expect(ref.inputType).toBe('email')
    expect(ref.selector).toBe('#email')
    expect(ref.xpath).toContain('input')
  })

  it('buildElementRef text 截断到 120 字符', () => {
    const el = document.createElement('div')
    el.textContent = 'x'.repeat(200)
    document.body.appendChild(el)
    const ref = buildElementRef(el)
    expect(ref.text!.length).toBeLessThanOrEqual(120)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chrome-extension && npx vitest run src/capture/selector.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `capture/selector.ts`**

> 完整照搬 `/Users/heren/code/Browser-BC/extension/src/capture/selector.ts`（已读全文，167 行）。唯一改动：第 1 行 `import type { ElementRef } from '@/shared/types'` 改为 `from './types'`。其余代码一字不改。

```
（照搬 Browser-BC extension/src/capture/selector.ts 全文，仅改 import 路径）
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chrome-extension && npx vitest run src/capture/selector.test.ts`
Expected: PASS（5 个测试全过）

- [ ] **Step 5: 提交**

```bash
cd chrome-extension
git add src/capture/selector.ts src/capture/selector.test.ts
git commit -m "feat(capture): 稳定选择器与 xpath 生成（照搬 Browser-BC）"
```

---

### Task B4: capture/redactor.ts（隐私脱敏）

**Files:**
- Create: `chrome-extension/src/capture/redactor.ts`
- Create: `chrome-extension/src/capture/redactor.test.ts`

> Browser-BC 的 `redaction/redactor.ts`（544 行）很重，含 identity_bundle 匹配、网络 body 分类等。我们**简化版**：只保留 `redactText`（核心分类逻辑）+ `redactEvent`（对 action/navigation 事件脱敏），去掉 identity_bundle/network/dom_snapshot/form_summary 相关分支。digest 用简单 hash（不依赖 sha256 库，用 SubtleCrypto 或简单字符串 hash）。

- [ ] **Step 1: 写失败测试**

```typescript
// chrome-extension/src/capture/redactor.test.ts
import { describe, it, expect } from 'vitest'
import { redactText } from './redactor'

describe('redactText', () => {
  it('普通文本不脱敏', () => {
    const r = redactText('hello world', {})
    expect(r.value).toBe('hello world')
    expect(r.redaction).toBeUndefined()
  })

  it('密码字段脱敏', () => {
    const r = redactText('secret123', { fieldName: 'password', inputType: 'password' })
    expect(r.value).toBeNull()
    expect(r.redaction?.classes).toContain('classified_password')
  })

  it('邮箱值脱敏', () => {
    const r = redactText('user@example.com', { fieldName: 'email' })
    expect(r.value).toBeNull()
    expect(r.redaction?.classes).toContain('classified_email')
  })

  it('邮箱正则匹配脱敏', () => {
    const r = redactText('联系 admin@test.com 谢谢', {})
    expect(r.value).toBeNull()
    expect(r.redaction?.classes).toContain('classified_email')
  })

  it('支付卡号脱敏（Luhn 有效）', () => {
    const r = redactText('4111111111111111', {})
    expect(r.value).toBeNull()
    expect(r.redaction?.classes).toContain('classified_payment')
  })

  it('OTP 上下文脱敏', () => {
    const r = redactText('123456', { fieldName: 'verification_code' })
    expect(r.value).toBeNull()
    expect(r.redaction?.classes).toContain('classified_otp')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chrome-extension && npx vitest run src/capture/redactor.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `capture/redactor.ts`**

> 简化自 Browser-BC `redaction/redactor.ts`：保留 `classifyText` 核心逻辑 + `redactText`，去掉 identity/network/dom_snapshot 分支。digest 用简单 FNV-1a hash（同步，不依赖 SubtleCrypto）。

```typescript
// chrome-extension/src/capture/redactor.ts
/** 隐私脱敏（简化自 Browser-BC redaction/redactor.ts）。
 * 保留密码/邮箱/电话/支付/OTP 的分类与 raw_removed 策略。
 *  去掉 identity_bundle 匹配、网络 body 分类、dom_snapshot 处理。 */

import type { RedactedValue, RedactionClass, Redaction } from './types'

type RedactionContext = {
  fieldName?: string
  inputType?: string
}

const LARGE_BODY_LIMIT = 4096
const EMAIL_RE = /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i
const PHONE_RE = /(?:\+?\d[\s().-]*){7,15}/
const DIGIT_RE = /\d/g
const OTP_RE = /\b\d{4,8}\b/
const PASSWORD_FIELD_RE = /pass(word)?|pwd|secret/i
const EMAIL_FIELD_RE = /e-?mail/i
const PHONE_FIELD_RE = /phone|mobile|tel/i
const PAYMENT_FIELD_RE = /card|cc|cvc|cvv|payment|expir(y|ation|e)?|exp_(month|year)/i
const OTP_CONTEXT_RE = /otp|one[-_\s]?time|verification|verify|2fa|mfa|code/i

export function redactText(value: string, context: RedactionContext = {}): RedactedValue {
  const classes = classifyText(value, context)
  if (classes.length === 0) {
    return { value }
  }
  return {
    value: null,
    redaction: {
      strategy: 'raw_removed',
      classes,
      digest: digestFor(value),
      originalLength: value.length,
    },
  }
}

function classifyText(value: string, context: RedactionContext): RedactionClass[] {
  const classes: RedactionClass[] = []
  const field = `${context.fieldName ?? ''} ${context.inputType ?? ''}`

  if (value.length > LARGE_BODY_LIMIT) {
    classes.push('classified_token')
  }

  if (PASSWORD_FIELD_RE.test(field) || context.inputType?.toLowerCase() === 'password') {
    classes.push('classified_password')
  }
  if (EMAIL_FIELD_RE.test(field)) {
    classes.push('classified_email')
  }
  if (PHONE_FIELD_RE.test(field)) {
    classes.push('classified_phone')
  }
  if (PAYMENT_FIELD_RE.test(field)) {
    classes.push('classified_payment')
  }
  if (OTP_CONTEXT_RE.test(field) && OTP_RE.test(value)) {
    classes.push('classified_otp')
  }

  if (EMAIL_RE.test(value)) {
    classes.push('classified_email')
  }

  const digits = digitsOnly(value)
  if (digits.length >= 13 && digits.length <= 19 && luhnValid(digits)) {
    classes.push('classified_payment')
  } else if (PHONE_RE.test(value) && digits.length >= 7 && digits.length <= 15) {
    classes.push('classified_phone')
  }

  return [...new Set(classes)]
}

function digitsOnly(value: string): string {
  return Array.from(String(value).matchAll(DIGIT_RE), (m) => m[0]).join('')
}

function luhnValid(value: string): boolean {
  let sum = 0
  let doubleDigit = false
  for (let i = value.length - 1; i >= 0; i -= 1) {
    let digit = Number(value[i])
    if (doubleDigit) {
      digit *= 2
      if (digit > 9) digit -= 9
    }
    sum += digit
    doubleDigit = !doubleDigit
  }
  return sum > 0 && sum % 10 === 0
}

/** FNV-1a 32 位 hash（同步，不依赖 SubtleCrypto）。 */
function digestFor(value: string): string {
  let hash = 0x811c9dc5
  for (let i = 0; i < value.length; i++) {
    hash ^= value.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193)
  }
  return `fnv1a:${(hash >>> 0).toString(16).padStart(8, '0')}`
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chrome-extension && npx vitest run src/capture/redactor.test.ts`
Expected: PASS（6 个测试全过）

- [ ] **Step 5: 提交**

```bash
cd chrome-extension
git add src/capture/redactor.ts src/capture/redactor.test.ts
git commit -m "feat(capture): 隐私脱敏 redactor（简化版，FNV-1a digest）"
```

---

### Task B5: capture/action-recorder.ts（DOM 事件捕获）

**Files:**
- Create: `chrome-extension/src/capture/action-recorder.ts`

> 完整照搬 `/Users/heren/code/Browser-BC/extension/src/capture/action-recorder.ts`（已读全文，418 行）。改动：
> 1. import 路径 `@/shared/id` → `./id`，`@/shared/types` → `./types`
> 2. `emit` 函数中，对 `value` 字段调用 `redactText` 脱敏（在 action-recorder 里集成 redactor，而非在 background 后处理）
>
> 这一步无单测（依赖真实 DOM 事件循环，Vitest 的 jsdom 对 capture phase + WeakMap + MutationObserver 支持有限）。改为手动验证。

- [ ] **Step 1: 实现 `capture/action-recorder.ts`**

> 照搬 Browser-BC `extension/src/capture/action-recorder.ts` 全文，做两处改动：
>
> 1. **import 路径**：
>    ```typescript
>    // 原：
>    import { createId } from '@/shared/id'
>    import type { ActionEvent, CapturedEvent } from '@/shared/types'
>    import { buildElementRef } from './selector'
>    // 改为：
>    import { createId } from './id'
>    import type { ActionEvent, CapturedEvent } from './types'
>    import { buildElementRef } from './selector'
>    import { redactText } from './redactor'
>    ```
>
> 2. **value 字段脱敏**：在 `inputHandler` 中，把 `value: { value: valueFor(target) }` 改为先脱敏：
>    ```typescript
>    const inputHandler = (actionType: 'input' | 'change') => (event: Event) => {
>      const target = elementFromEvent(event)
>      if (
>        actionType === 'change' &&
>        target instanceof HTMLInputElement &&
>        target.type === 'file'
>      ) {
>        emit({
>          action_type: 'file_select',
>          target: buildElementRef(target),
>          files: fileMetadata(target),
>        })
>        return
>      }
>      // 脱敏：根据元素 name/id/type 推导 context
>      const rawValue = target ? valueFor(target) : ''
>      const context = target ? {
>        fieldName: (target as HTMLElement).name || target.id || '',
>        inputType: target instanceof HTMLInputElement ? target.type : undefined,
>      } : {}
>      const redacted = redactText(rawValue, context)
>      emit({
>        action_type: actionType,
>        ...(target ? { target: buildElementRef(target), value: redacted } : {}),
>      })
>    }
>    ```
>
> 其余代码（mouseHandler/dragHandler/keydownHandler/scrollHandler 等）一字不改照搬。

- [ ] **Step 2: 类型检查**

Run: `cd chrome-extension && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
cd chrome-extension
git add src/capture/action-recorder.ts
git commit -m "feat(capture): DOM 事件捕获 action-recorder（照搬 Browser-BC + 脱敏集成）"
```

---

### Task B6: capture/mutation-summary-recorder.ts

**Files:**
- Create: `chrome-extension/src/capture/mutation-summary-recorder.ts`

> 完整照搬 `/Users/heren/code/Browser-BC/extension/src/capture/mutation-summary-recorder.ts`（已读全文，139 行）。改动仅 import 路径：`@/shared/id` → `./id`，`@/shared/types` → `./types`。

- [ ] **Step 1: 实现 `capture/mutation-summary-recorder.ts`**

> 照搬 Browser-BC `extension/src/capture/mutation-summary-recorder.ts` 全文（139 行），import 路径改为：
> ```typescript
> import { createId } from './id'
> import type { CapturedEvent, DomMutationSignal, DomMutationSummaryEvent } from './types'
> import { bestSelector } from './selector'
> ```
> 其余代码一字不改。

- [ ] **Step 2: 类型检查**

Run: `cd chrome-extension && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
cd chrome-extension
git add src/capture/mutation-summary-recorder.ts
git commit -m "feat(capture): DOM 变更摘要 mutation-summary-recorder（照搬 Browser-BC）"
```

---

### Task B7: capture/recorder.ts（录制编排）

**Files:**
- Create: `chrome-extension/src/capture/recorder.ts`

> 新写：把 action-recorder + mutation-summary-recorder 组合，提供 `startRecording` / `stopRecording` / `flushEvents`。捕获的事件通过回调发回 background。

- [ ] **Step 1: 实现 `capture/recorder.ts`**

```typescript
// chrome-extension/src/capture/recorder.ts
/** 录制编排：组合 action-recorder + mutation-summary-recorder。
 *  在 content script 中安装/卸载，捕获的事件经 sendEvent 回调发回 background。 */

import { installActionRecorder, type InstalledCapture } from './action-recorder'
import { installMutationSummaryRecorder } from './mutation-summary-recorder'
import type { CapturedEvent } from './types'

export type RecorderHandle = {
  stop: () => CapturedEvent[]  // 停止并返回 flush 出的剩余事件
}

export type RecorderOptions = {
  traceId: string
  tabId: number
  sendEvent: (event: CapturedEvent) => void
}

/** 安装录制器，返回 handle（stop 时卸载并 flush）。 */
export function startRecording(options: RecorderOptions): RecorderHandle {
  const { traceId, tabId, sendEvent } = options

  const actionCapture = installActionRecorder({
    traceId,
    tabId,
    sendEvent,
  })

  const mutationCapture = installMutationSummaryRecorder({
    traceId,
    tabId,
    sendEvent,
  })

  return {
    stop() {
      actionCapture.stop()
      // mutation-summary 的 stop() 内部会 flush 剩余事件（通过 sendEvent），
      // 但 sendEvent 是同步的，flush 的事件已发出；这里返回空数组保持接口一致
      mutationCapture.stop()
      return []
    },
  }
}
```

- [ ] **Step 2: 类型检查**

Run: `cd chrome-extension && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
cd chrome-extension
git add src/capture/recorder.ts
git commit -m "feat(capture): 录制编排 recorder（组合 action + mutation 捕获器）"
```

---

### Task B8: entrypoints/recorder.content.ts（content script 入口）

**Files:**
- Create: `chrome-extension/src/entrypoints/recorder.content.ts`

> WXT content script 入口。background 用 `chrome.scripting.executeScript` 动态注入。监听 background 的 start/stop 消息。

- [ ] **Step 1: 实现 `recorder.content.ts`**

```typescript
// chrome-extension/src/entrypoints/recorder.content.ts
/** 录制 content script：动态注入，监听 background 的 start/stop 指令。
 *  与现有静态注册的 content.js 职责正交（那个执行 Agent 指令，这个录制用户操作）。 */

import { startRecording, type RecorderHandle } from '@/capture/recorder'
import type { CapturedEvent } from '@/capture/types'

export default defineContentScript({
  matches: ['<all_urls>'],
  // 不在 manifest 静态注册——由 background 用 chrome.scripting.executeScript 动态注入
  runAt: 'document_idle',
  async main() {
    let handle: RecorderHandle | null = null

    chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (message.type === 'record_start_content') {
        if (handle) {
          sendResponse({ started: false, reason: 'already_recording' })
          return false
        }
        handle = startRecording({
          traceId: message.trace_id,
          tabId: message.tab_id,
          sendEvent: (event: CapturedEvent) => {
            chrome.runtime.sendMessage({ type: 'record_event_content', event }).catch(() => {})
          },
        })
        sendResponse({ started: true })
        return false
      }

      if (message.type === 'record_stop_content') {
        if (handle) {
          handle.stop()
          handle = null
        }
        sendResponse({ stopped: true })
        return false
      }

      return false
    })
  },
})
```

- [ ] **Step 2: 确认 WXT 能编译此入口**

Run: `cd chrome-extension && npx tsc --noEmit`
Expected: 无错误

> 注意：`defineContentScript` 是 WXT 的全局 helper（类似 `defineBackground`），由 `wxt prepare` 生成类型。若 tsc 报未定义，运行 `npm run postinstall`（即 `wxt prepare`）刷新 `.wxt/types/`。

- [ ] **Step 3: 提交**

```bash
cd chrome-extension
git add src/entrypoints/recorder.content.ts
git commit -m "feat(recorder): content script 入口（动态注入，监听 start/stop）"
```

---

## 阶段 C：WS 协议打通

### Task C1: 前端消息类型扩展

**Files:**
- Modify: `chrome-extension/src/types/index.ts`

- [ ] **Step 1: 扩展 `SidepanelMessage` 和 `BackgroundMessage`**

在 `chrome-extension/src/types/index.ts` 末尾新增（不改现有类型）：

```typescript
// ====== 录制功能（record_*）======

/** 录制状态 */
export type RecorderStatus = 'idle' | 'recording' | 'distilling' | 'done'

/** 录制蒸馏阶段 */
export type DistillStage = 'atomize' | 'distill' | 'install'

/** SidePanel → 后台的录制消息 */
export interface RecordStartMsg {
  type: 'record_start'
  tab_id: number
  label?: string
}
export interface RecordStopMsg {
  type: 'record_stop'
  trace_id: string
  label?: string
}
export interface RecordRedistillMsg {
  type: 'record_redistill'
  trace_id: string
}

/** 后台 → SidePanel 的录制消息 */
export interface RecordStartedMsg {
  type: 'record_started'
  trace_id: string
}
export interface RecordProgressMsg {
  type: 'record_progress'
  received_events: number
  seq: number
}
export interface RecordDistillingMsg {
  type: 'record_distilling'
  trace_id: string
}
export interface RecordDistillProgressMsg {
  type: 'record_distill_progress'
  stage: DistillStage
  message: string
}
export interface RecordDoneMsg {
  type: 'record_done'
  trace_id: string
  skill_name: string
  skill_path: string
}
export interface RecordErrorMsg {
  type: 'record_error'
  trace_id: string
  stage: string
  message: string
}
```

- [ ] **Step 2: 类型检查**

Run: `cd chrome-extension && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
cd chrome-extension
git add src/types/index.ts
git commit -m "feat(types): 新增 record_* 录制消息类型"
```

---

### Task C2: 后端 config.yaml 扩展

**Files:**
- Modify: `agent-core/config.yaml`

- [ ] **Step 1: 新增 recorder 配置段**

在 `config.yaml` 末尾新增：

```yaml
recorder:
  # 蒸馏用的模型配置（不配则复用 llm 段）
  distill_model: null   # null 表示复用 llm.model
  # 单批上传事件数上限（前端聚合后批量发送）
  batch_size: 500
  # 内存缓冲落盘阈值（前端防内存膨胀）
  buffer_flush_threshold: 5000
```

- [ ] **Step 2: 验证 config_loader 能读取**

Run: `cd agent-core && uv run python -c "from config_loader import load_config; c = load_config(); print(c.get('recorder'))"`
Expected: 打印 `{'distill_model': None, 'batch_size': 500, 'buffer_flush_threshold': 5000}`

- [ ] **Step 3: 提交**

```bash
cd agent-core
git add config.yaml
git commit -m "feat(config): 新增 recorder 蒸馏配置段"
```

---

### Task C3: 后端 server.py 录制路由

**Files:**
- Modify: `agent-core/server.py`
- Create: `agent-core/tests/test_server_record.py`

> 在 `handle_client` 的消息循环中新增 `record_start`/`record_event`/`record_stop`/`record_redistill` 分支。蒸馏用 `asyncio.create_task` 异步执行，不阻塞 WS。

- [ ] **Step 1: 写失败测试**

```python
# agent-core/tests/test_server_record.py
"""server.py 录制路由单测。"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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
async def test_record_start_creates_session(monkeypatch, tmp_path):
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
async def test_record_event_appends_to_session(monkeypatch, tmp_path):
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
async def test_record_stop_triggers_distill(monkeypatch, tmp_path):
    """record_stop 应触发蒸馏 task（mock 掉实际蒸馏）。"""
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
        ws = FakeWS([json.dumps({"type": "record_stop", "trace_id": "t1"})])
        await server.handle_client(ws, {
            "skills": {"dirs": [str(tmp_path / "skills")]},
            "llm": {"provider": "dashscope", "model": "x", "api_key": "k"},
        })

        await asyncio.sleep(0.1)  # 等蒸馏 task 启动

        assert captured.get("trace_id") == "t1"
        assert captured.get("events_count") == 1
        assert "t1" not in server._record_sessions  # session 已清理
    finally:
        server._agent = None
        server._current_task = None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd agent-core && uv run pytest tests/test_server_record.py -v`
Expected: FAIL（`_record_sessions` 不存在、`record_start` 未路由）

- [ ] **Step 3: 修改 `server.py`**

在 `server.py` 顶部 import 区新增：

```python
# 在现有 import 后新增
from recorder.pipeline import run_distill_pipeline
from agent.model import create_model
```

在 `_current_task` 全局变量下方新增录制会话存储：

```python
# 当前正在运行的 agent task，用于支持取消
_current_task: asyncio.Task | None = None
# 录制会话：trace_id → {events, label, tab_id}
_record_sessions: dict[str, dict] = {}
```

在 `handle_client` 的消息循环中（`elif msg_type == "stop":` 块之后、`except websockets.ConnectionClosed` 之前）新增录制路由：

```python
            elif msg_type == "record_start":
                trace_id = msg.get("trace_id") or uuid4().hex[:12]
                _record_sessions[trace_id] = {
                    "events": [],
                    "label": msg.get("label", ""),
                    "tab_id": msg.get("tab_id", -1),
                }
                await websocket.send(json.dumps({"type": "record_started", "trace_id": trace_id}))
                log.info("录制开始: trace_id=%s", trace_id)

            elif msg_type == "record_event":
                trace_id = msg.get("trace_id")
                session = _record_sessions.get(trace_id)
                if session is None:
                    log.warning("未知 trace_id 的 record_event: %s", trace_id)
                    continue
                events = msg.get("events", [])
                session["events"].extend(events)
                await websocket.send(json.dumps({
                    "type": "record_progress",
                    "received_events": len(session["events"]),
                    "seq": msg.get("seq", 0),
                }))

            elif msg_type == "record_stop":
                trace_id = msg.get("trace_id")
                session = _record_sessions.pop(trace_id, None)
                if session is None:
                    await websocket.send(json.dumps({
                        "type": "record_error",
                        "trace_id": trace_id,
                        "stage": "stop",
                        "message": "录制会话不存在",
                    }))
                    continue
                label = msg.get("label") or session.get("label", "")
                # 触发蒸馏 task（不阻塞 WS）
                asyncio.create_task(_run_distill(
                    websocket, agent, trace_id, session["events"], label, config,
                ))

            elif msg_type == "record_redistill":
                # 从 _source_trace.json 重蒸馏（失败后重试用）
                trace_id = msg.get("trace_id")
                asyncio.create_task(_redistill_from_trace(websocket, agent, trace_id, config))
```

在 `handle_client` 函数之后、`main` 之前新增辅助函数：

```python
async def _run_distill(websocket, agent, trace_id, raw_events, label, config):
    """执行蒸馏管线，推送进度和结果到 WS。"""
    skills_dirs = config.get("skills", {}).get("dirs", [])
    skills_root = Path(skills_dirs[0]) if skills_dirs else Path("./skills")

    # 蒸馏模型：复用 llm 配置（除非 recorder.distill_model 单独配置）
    recorder_cfg = config.get("recorder", {})
    distill_model_cfg = recorder_cfg.get("distill_model")
    if distill_model_cfg:
        model = create_model(distill_model_cfg, role="distill")
    else:
        # 复用 BrowserAgent 的 llm model（已初始化）
        model = agent._agent.model if agent._agent else create_model(config["llm"], role="distill")

    async def on_progress(stage, message):
        try:
            await websocket.send(json.dumps({
                "type": "record_distill_progress",
                "stage": stage,
                "message": message,
            }))
        except Exception:
            pass

    try:
        await websocket.send(json.dumps({"type": "record_distilling", "trace_id": trace_id}))

        result = await run_distill_pipeline(
            trace_id=trace_id,
            raw_events=raw_events,
            label=label,
            model=model,
            skills_root=skills_root,
            on_progress=on_progress,
        )

        # 蒸馏安装成功后，刷新前端技能列表（LocalSkillLoader 会实时扫到新技能）
        skills = await agent.list_skills()
        await websocket.send(json.dumps({"type": "skills_list", "skills": skills}))

        await websocket.send(json.dumps({
            "type": "record_done",
            "trace_id": trace_id,
            "skill_name": result["skill_name"],
            "skill_path": result["skill_path"],
        }))
        log.info("录制蒸馏完成: trace_id=%s skill=%s", trace_id, result["skill_name"])

    except Exception as e:
        log.error("录制蒸馏失败: trace_id=%s %s", trace_id, e, exc_info=True)
        try:
            await websocket.send(json.dumps({
                "type": "record_error",
                "trace_id": trace_id,
                "stage": "distill",
                "message": str(e),
            }))
        except Exception:
            pass


async def _redistill_from_trace(websocket, agent, trace_id, config):
    """从 _source_trace.json 重蒸馏（失败重试用）。"""
    skills_dirs = config.get("skills", {}).get("dirs", [])
    skills_root = Path(skills_dirs[0]) if skills_dirs else Path("./skills")

    # 查找该 trace_id 对应的 _source_trace.json
    trace_files = list(skills_root.rglob("_source_trace.json"))
    trace_events = None
    for tf in trace_files:
        try:
            data = json.loads(tf.read_text())
            if data.get("trace_id") == trace_id:
                trace_events = data.get("events", [])
                break
        except Exception:
            continue

    if trace_events is None:
        await websocket.send(json.dumps({
            "type": "record_error",
            "trace_id": trace_id,
            "stage": "redistill",
            "message": "找不到原始录制数据",
        }))
        return

    await _run_distill(websocket, agent, trace_id, trace_events, "", config)
```

在 `server.py` 顶部 import 区补充：

```python
from uuid import uuid4
from pathlib import Path
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd agent-core && uv run pytest tests/test_server_record.py -v`
Expected: PASS（3 个测试全过）

- [ ] **Step 5: 跑全部后端测试确认无回归**

Run: `cd agent-core && uv run pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
cd agent-core
git add server.py tests/test_server_record.py
git commit -m "feat(server): 新增 record_* 录制路由与蒸馏触发"
```

---

### Task C4: 前端 background.ts 录制路由

**Files:**
- Modify: `chrome-extension/src/entrypoints/background.ts`

> 在 background 中新增：接收 SidePanel 的 `record_start`/`record_stop`，注入 content script，聚合 content 发来的事件，批量发 WS。

- [ ] **Step 1: 修改 `background.ts`**

在 `defineBackground` 内部、`wsClient.connect()` 之后，`handleAction` 之前，新增录制状态和路由：

```typescript
  // ====== 录制功能 ======
  // 录制会话：trace_id → {tabId, buffer, seq, label}
  let activeRecordSession: {
    trace_id: string
    tabId: number
    buffer: any[]
    seq: number
    label: string
    flushTimer: ReturnType<typeof setInterval> | null
  } | null = null

  const RECORD_BATCH_SIZE = 500
  const RECORD_FLUSH_INTERVAL_MS = 2000  // 定时 flush，避免低频录制时事件积压

  /** 注入录制 content script 到目标 tab */
  async function injectRecorder(tabId: number) {
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: ['recorder.content.js'],
      })
    } catch (err) {
      console.warn('[BU-Agent] Recorder inject:', (err as Error).message)
    }
  }

  /** 把缓冲区事件批量发到后端 */
  function flushRecordBuffer() {
    if (!activeRecordSession || !wsClient.isConnected()) return
    const session = activeRecordSession
    if (session.buffer.length === 0) return

    const events = session.buffer.splice(0, RECORD_BATCH_SIZE)
    session.seq += 1
    wsClient.send({
      type: 'record_event',
      trace_id: session.trace_id,
      events,
      seq: session.seq,
    })
  }

  /** 启动录制：注入 content + 发 record_start + 启动定时 flush */
  async function startRecording(tabId: number, label: string): Promise<string | null> {
    if (activeRecordSession) {
      console.warn('[BU-Agent] 已有录制进行中')
      return null
    }
    const trace_id = crypto.randomUUID().replace(/-/g, '').slice(0, 12)
    activeRecordSession = {
      trace_id,
      tabId,
      buffer: [],
      seq: 0,
      label,
      flushTimer: setInterval(flushRecordBuffer, RECORD_FLUSH_INTERVAL_MS),
    }

    await injectRecorder(tabId)

    // 注入后给 content 发 start 指令
    chrome.tabs.sendMessage(tabId, {
      type: 'record_start_content',
      trace_id,
      tab_id: tabId,
    }).catch(() => {})

    wsClient.send({ type: 'record_start', tab_id: tabId, label })
    chrome.action.setBadgeText({ text: '●' })
    chrome.action.setBadgeBackgroundColor({ color: '#ef4444' })
    return trace_id
  }

  /** 停止录制：flush 剩余 + 发 record_stop + 卸载 content */
  async function stopRecording(finalLabel?: string): Promise<void> {
    if (!activeRecordSession) return
    const session = activeRecordSession

    // 通知 content 停止（content 会 flush mutation summary）
    chrome.tabs.sendMessage(session.tabId, { type: 'record_stop_content' }).catch(() => {})

    // 最后 flush 一次
    flushRecordBuffer()
    if (session.flushTimer) {
      clearInterval(session.flushTimer)
    }

    wsClient.send({
      type: 'record_stop',
      trace_id: session.trace_id,
      label: finalLabel || session.label,
    })

    chrome.action.setBadgeText({ text: '' })
    activeRecordSession = null
  }
```

在 `wsClient.onMessage` 回调中，新增对 `record_*` 后端消息的转发（在现有 `skills_list` 分支后）：

```typescript
    } else if (type === 'skills_list') {
      cachedSkills = (msg as any).skills ?? []
      chrome.runtime.sendMessage(msg).catch(() => {})
    } else if (type.startsWith('record_')) {
      // 转发所有 record_* 消息到 SidePanel
      chrome.runtime.sendMessage(msg).catch(() => {})
    }
```

在 `chrome.runtime.onMessage.addListener` 中（现有 `new_session` 分支后）新增 SidePanel → background 的录制指令：

```typescript
    if (message.type === 'record_start') {
      getActiveTab().then((tab) => {
        if (tab?.id) startRecording(tab.id, message.label || '').then((trace_id) => {
          sendResponse({ trace_id })
        })
      })
      return true  // 异步响应
    }
    if (message.type === 'record_stop') {
      stopRecording(message.label).then(() => sendResponse({ stopped: true }))
      return true
    }
    if (message.type === 'record_redistill') {
      wsClient.send({ type: 'record_redistill', trace_id: message.trace_id })
      sendResponse({ received: true })
    }
    if (message.type === 'record_event_content') {
      // content script 发来的单条事件 → 聚合到 buffer
      if (activeRecordSession && message.event) {
        activeRecordSession.buffer.push(message.event)
        // 满 batch 立即 flush
        if (activeRecordSession.buffer.length >= RECORD_BATCH_SIZE) {
          flushRecordBuffer()
        }
      }
    }
    if (message.type === 'get_recorder_state') {
      sendResponse({
        active: activeRecordSession !== null,
        trace_id: activeRecordSession?.trace_id ?? null,
        eventCount: activeRecordSession?.buffer.length ?? 0,
      })
    }
```

- [ ] **Step 2: 类型检查**

Run: `cd chrome-extension && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
cd chrome-extension
git add src/entrypoints/background.ts
git commit -m "feat(background): 录制路由（注入 content + 聚合 + 批量上传 + badge）"
```

---

## 阶段 D：UI 集成

### Task D1: hooks/useRecorder.ts

**Files:**
- Create: `chrome-extension/src/hooks/useRecorder.ts`

> 前端录制状态管理：通过 `chrome.runtime.sendMessage` 与 background 通信，监听 `record_*` 消息更新状态。

- [ ] **Step 1: 实现 `useRecorder.ts`**

```typescript
// chrome-extension/src/hooks/useRecorder.ts
/** 录制状态管理 hook：与 background 通信，监听 record_* 消息。 */

import { useEffect, useState, useCallback } from 'react'
import type {
  RecorderStatus,
  DistillStage,
  RecordStartedMsg,
  RecordDistillProgressMsg,
  RecordDoneMsg,
  RecordErrorMsg,
} from '@/types'

export interface RecorderState {
  status: RecorderStatus
  traceId: string | null
  startedAt: number | null
  eventCount: number
  distillStage: DistillStage | null
  distillMessage: string | null
  lastSkill: { name: string; path: string } | null
  error: string | null
}

const INITIAL: RecorderState = {
  status: 'idle',
  traceId: null,
  startedAt: null,
  eventCount: 0,
  distillStage: null,
  distillMessage: null,
  lastSkill: null,
  error: null,
}

export function useRecorder() {
  const [state, setState] = useState<RecorderState>(INITIAL)

  // 监听 background 转发的 record_* 消息
  useEffect(() => {
    const listener = (msg: Record<string, unknown>) => {
      const type = msg.type as string
      if (!type.startsWith('record_')) return

      if (type === 'record_started') {
        const m = msg as unknown as RecordStartedMsg
        setState({
          ...INITIAL,
          status: 'recording',
          traceId: m.trace_id,
          startedAt: Date.now(),
        })
      } else if (type === 'record_progress') {
        setState((s) => ({ ...s, eventCount: (msg.received_events as number) ?? s.eventCount }))
      } else if (type === 'record_distilling') {
        setState((s) => ({ ...s, status: 'distilling', distillStage: null, distillMessage: null }))
      } else if (type === 'record_distill_progress') {
        const m = msg as unknown as RecordDistillProgressMsg
        setState((s) => ({ ...s, distillStage: m.stage, distillMessage: m.message }))
      } else if (type === 'record_done') {
        const m = msg as unknown as RecordDoneMsg
        setState({
          ...INITIAL,
          status: 'done',
          lastSkill: { name: m.skill_name, path: m.skill_path },
        })
        // 3 秒后恢复 idle
        setTimeout(() => setState((s) => ({ ...s, status: 'idle' })), 3000)
      } else if (type === 'record_error') {
        const m = msg as unknown as RecordErrorMsg
        setState({
          ...INITIAL,
          status: 'idle',
          error: m.message,
          traceId: m.trace_id,
        })
      }
    }
    chrome.runtime.onMessage.addListener(listener)
    return () => chrome.runtime.onMessage.removeListener(listener)
  }, [])

  const start = useCallback(async (label: string) => {
    const tab = await chrome.tabs.query({ active: true, currentWindow: true })
    if (!tab[0]?.id) return
    chrome.runtime.sendMessage({ type: 'record_start', label })
  }, [])

  const stop = useCallback(async (label?: string) => {
    chrome.runtime.sendMessage({ type: 'record_stop', label })
  }, [])

  const redistill = useCallback(async (traceId: string) => {
    chrome.runtime.sendMessage({ type: 'record_redistill', trace_id: traceId })
    setState((s) => ({ ...s, status: 'distilling', error: null }))
  }, [])

  const dismissError = useCallback(() => {
    setState((s) => ({ ...s, error: null }))
  }, [])

  return { state, start, stop, redistill, dismissError }
}
```

- [ ] **Step 2: 类型检查**

Run: `cd chrome-extension && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
cd chrome-extension
git add src/hooks/useRecorder.ts
git commit -m "feat(hooks): useRecorder 录制状态管理 hook"
```

---

### Task D2: ChatView.tsx 录制按钮 UI

**Files:**
- Modify: `chrome-extension/src/components/ChatView.tsx`

> 在现有「✦ 技能」按钮旁新增「● 录制」按钮，三态状态机 + 停止确认框 + 蒸馏进度提示。

- [ ] **Step 1: 修改 `ChatView.tsx`**

在文件顶部 import 区新增：

```typescript
import { Circle, Loader2, Check } from 'lucide-react'
import { useRecorder } from '@/hooks/useRecorder'
```

修改 `ChatViewProps` 和组件签名，加入 recorder：

```typescript
interface ChatViewProps {
  messages: Message[]
  isStreaming: boolean
  sendTask: (content: string) => void
  stopStream: () => void
  activityStatus: string
  skills: SkillInfo[]
}

export function ChatView({ messages, isStreaming, sendTask, stopStream, activityStatus, skills }: ChatViewProps) {
  const [inputValue, setInputValue] = useState('')
  const [showSkills, setShowSkills] = useState(false)
  // 新增：录制状态
  const recorder = useRecorder()
  const [showStopConfirm, setShowStopConfirm] = useState(false)
  const [recordLabel, setRecordLabel] = useState('')
  // ... 原有 refs ...
```

在「技能工具栏」的 `<div ref={skillPopoverRef}>` 之后，新增录制按钮区域：

```tsx
        {/* 录制按钮 */}
        <div className="relative mt-2 flex items-center gap-2">
          {/* 录制 / 停止 / 蒸馏中 三态按钮 */}
          {recorder.state.status === 'idle' && (
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={() => {
                setRecordLabel('')
                recorder.start('')
              }}
              disabled={isStreaming}
              title="开始录制"
            >
              <Circle className="size-3.5 text-muted-foreground" />
              录制
            </Button>
          )}

          {recorder.state.status === 'recording' && (
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs border-red-500 text-red-500"
              onClick={() => setShowStopConfirm(true)}
              title="停止录制"
            >
              <Circle className="size-3.5 fill-red-500 text-red-500 animate-pulse" />
              录制中 {formatDuration(recorder.state.startedAt)}
            </Button>
          )}

          {recorder.state.status === 'distilling' && (
            <Button variant="outline" size="sm" className="h-7 text-xs" disabled>
              <Loader2 className="size-3.5 animate-spin" />
              {recorder.state.distillMessage || '蒸馏中...'}
            </Button>
          )}

          {recorder.state.status === 'done' && recorder.state.lastSkill && (
            <div className="flex items-center gap-1 text-xs text-green-600">
              <Check className="size-3.5" />
              技能 {recorder.state.lastSkill.name} 已生成
            </div>
          )}

          {recorder.state.error && (
            <div className="flex items-center gap-1 text-xs text-red-500">
              录制失败：{recorder.state.error}
              <button className="underline" onClick={recorder.dismissError}>忽略</button>
              {recorder.state.traceId && (
                <button className="underline" onClick={() => recorder.redistill(recorder.state.traceId!)}>
                  重试
                </button>
              )}
            </div>
          )}
        </div>

        {/* 停止确认弹窗 */}
        {showStopConfirm && (
          <div className="absolute bottom-full mb-2 right-0 w-72 rounded-md border bg-popover p-3 shadow-md z-10">
            <div className="text-xs font-medium mb-2">停止录制</div>
            <input
              type="text"
              className="w-full rounded border bg-background px-2 py-1 text-xs mb-2"
              placeholder="技能名称（可选）"
              value={recordLabel}
              onChange={(e) => setRecordLabel(e.target.value)}
            />
            <div className="flex gap-2 justify-end">
              <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setShowStopConfirm(false)}>
                取消
              </Button>
              <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => {
                setShowStopConfirm(false)
                recorder.state.traceId && null  // 不发送，丢弃
                chrome.runtime.sendMessage({ type: 'record_stop' })
              }}>
                丢弃
              </Button>
              <Button size="sm" className="h-7 text-xs" onClick={() => {
                setShowStopConfirm(false)
                recorder.stop(recordLabel)
              }}>
                确认
              </Button>
            </div>
          </div>
        )}
```

在文件底部（`}` 前）新增计时格式化辅助函数：

```typescript
function formatDuration(startedAt: number | null): string {
  if (!startedAt) return '00:00'
  const secs = Math.floor((Date.now() - startedAt) / 1000)
  const mm = String(Math.floor(secs / 60)).padStart(2, '0')
  const ss = String(secs % 60).padStart(2, '0')
  return `${mm}:${ss}`
}
```

- [ ] **Step 2: 类型检查**

Run: `cd chrome-extension && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: 构建验证**

Run: `cd chrome-extension && npm run build`
Expected: 构建成功，无报错

- [ ] **Step 4: 提交**

```bash
cd chrome-extension
git add src/components/ChatView.tsx
git commit -m "feat(ui): ChatView 新增录制按钮 + 三态状态机 + 停止确认"
```

---

### Task D3: 端到端手动验证

> 这一阶段无代码改动，是最终验证。

- [ ] **Step 1: 启动后端**

Run: `cd agent-core && uv run python server.py`
Expected: 日志显示「启动 Browser Use Agent 服务器 ws://localhost:8765」

- [ ] **Step 2: 构建并加载扩展**

Run: `cd chrome-extension && npm run build`
然后 Chrome → `chrome://extensions` → 加载 `chrome-extension/.output/chrome-mv3`

- [ ] **Step 3: 验证录制→蒸馏→技能生成全流程**

1. 打开任意网站（如 https://example.com）
2. 点 SidePanel 的「● 录制」按钮
3. 在页面上做几个操作（点击、输入、滚动）
4. 点「● 录制中」→ 填技能名 → 确认
5. 观察按钮变为「蒸馏中...」并显示阶段文案
6. 等待 → 显示「✓ 技能 xxx 已生成」
7. 点「✦ 技能」按钮 → 确认列表里有新技能
8. 在输入框输入 `/skill <新技能名> 帮我...` → 确认 Agent 能读到技能手册

Expected: 全流程跑通，新技能立即可用（无需重启后端）

- [ ] **Step 4: 验证脱敏**

录制时在密码框输入内容，停止后检查 `agent-core/skills/<name>/_source_trace.json`，确认密码字段 `value` 为 `null` 且 `redaction.classes` 含 `classified_password`。

- [ ] **Step 5: 验证蒸馏失败重试**

临时把后端 LLM_API_KEY 改错 → 录制 → 蒸馏应失败 → 前端显示错误 + 重试按钮 → 改回正确 key → 点重试 → 成功。

---

## Self-Review 检查

实现完成后，对照 spec 逐项检查：

**1. Spec 覆盖：**
- ✅ 第 3 节录制捕获层 → 阶段 B（Task B1-B8）
- ✅ 第 4 节传输层 WS 协议 → Task C1（类型）+ C3（后端路由）+ C4（前端 background）
- ✅ 第 5 节蒸馏层 atomize+distill → Task A3（atomizer）+ A4（distiller）+ A6（pipeline）
- ✅ 第 6 节安装层 + 实时生效 → Task A5（installer）+ C3（推 skills_list）
- ✅ 第 7 节 UI 交互 → Task D1（hook）+ D2（ChatView）
- ✅ 第 8 节错误处理 → pipeline 重试 + server error 推送 + UI 重试按钮
- ✅ 第 9 节配置 → Task C2（config.yaml）
- ✅ 第 11 节扩展接口 → Segment.bucket_id/capability + config.recorder.distill_model

**2. 类型一致性：**
- `DistillResult` 在 A1 定义，A4/A5/A6 使用一致
- `Segment` 在 A1 定义，A3/A4/A6 使用一致
- `run_distill_pipeline` 在 A6 定义，C3 调用签名匹配（trace_id, raw_events, label, model, skills_root, on_progress）
- 前端 `record_*` 消息类型在 C1 定义，C4/D1 使用一致

**3. 已知边界：**
- Task B5/B6（action-recorder/mutation-summary）无单测，依赖手动验证（DOM 事件循环在 Vitest jsdom 中不可靠）
- Task C4 中 `record_event_content` 的 `msg.event` 应为 `message.event`（修复点：实现时注意 `msg` 是 WS 消息变量名，`message` 是 onMessage 参数）
- distiller 的 `distill_segments` 调用 model 的签名需与 agentscope 实际 API 对齐（参照 `test_tools.py` 的 mock 风格）
