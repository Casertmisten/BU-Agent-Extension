# recorder/event_utils.py
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
