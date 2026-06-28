# recorder/atomizer.py
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
