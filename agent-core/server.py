# server.py
"""WebSocket 服务器入口。

职责：启动 WS 服务、路由消息到 BrowserAgent。
Agent 相关逻辑全部在 agent/ 模块中。
"""

import asyncio
import json
import time
from pathlib import Path
from uuid import uuid4
from dotenv import load_dotenv

load_dotenv()

import websockets

from agent import BrowserAgent
from agent.model import create_model
from browser.protocol import validate_message
from config_loader import load_config
from logger import get_logger, setup_logging
from recorder.pipeline import run_distill_pipeline

log = get_logger("server")

# 全局唯一的 Agent 实例
_agent: BrowserAgent | None = None
# 当前正在运行的 agent task，用于支持取消
_current_task: asyncio.Task | None = None
# 录制会话：trace_id → {events, label, tab_id}
_record_sessions: dict[str, dict] = {}


def _get_or_create_agent(config: dict) -> BrowserAgent:
    """获取或创建全局 BrowserAgent 实例（单例）。"""
    global _agent
    if _agent is None:
        _agent = BrowserAgent(config)
        _agent.init()
    return _agent


async def _run_agent_and_send(agent: BrowserAgent, text: str):
    """运行 Agent 并将流式结果推送到当前活跃的 WebSocket。

    使用 agent._current_ws 获取最新引用，确保重连后消息发到新 WS。
    """
    async for event in agent.run(text):
        ws = agent._current_ws
        if ws is None:
            break
        try:
            await ws.send(json.dumps(event))
        except Exception:
            pass


async def handle_client(websocket, config: dict):
    """处理 WebSocket 客户端（Chrome 扩展）连接。

    Chrome 扩展重连时只更新 WebSocket 引用，不重建 Agent。
    """
    agent = _get_or_create_agent(config)
    agent.attach_ws(websocket)

    # 握手后推送一次技能清单（技能是全局静态能力，与会话无关）。
    # 失败不阻断连接——前端 skills 保持空，按钮仍可点（显示空列表）。
    try:
        skills = await agent.list_skills()
        await websocket.send(json.dumps({"type": "skills_list", "skills": skills}))
        log.info("已推送技能清单，共 %d 个技能", len(skills))
    except Exception as e:
        log.warning("推送技能列表失败: %s", e)

    # 重连时通知前端之前的状态已丢失
    if agent._busy:
        log.warning("重连时 Agent 仍在执行，前端可能需要刷新状态")

    try:
        async for raw_message in websocket:
            try:
                msg = json.loads(raw_message)
                validate_message(msg)
            except (json.JSONDecodeError, ValueError) as e:
                log.warning("无效消息: %s", e)
                await websocket.send(json.dumps({"type": "error", "message": str(e)}))
                continue

            msg_type = msg["type"]

            if msg_type == "heartbeat":
                await websocket.send(json.dumps({"type": "heartbeat", "ts": time.time()}))

            elif msg_type == "result":
                agent.conn.handle_result(msg)

            elif msg_type == "page_ready":
                agent.viewport_info.update(msg.get("viewport", {}))
                log.debug("页面就绪, viewport: %s", agent.viewport_info)

            elif msg_type == "user_message":
                log.info("收到用户消息")
                global _current_task
                _current_task = asyncio.create_task(
                    _run_agent_and_send(agent, msg.get("content", ""))
                )

            elif msg_type == "new_session":
                if _current_task and not _current_task.done():
                    _current_task.cancel()
                    try:
                        await _current_task  # 确保旧任务彻底结束，避免残留 append 污染新上下文
                    except (asyncio.CancelledError, Exception):
                        pass  # 丢弃旧任务的取消/异常，不阻断新建会话；不吞 KeyboardInterrupt/SystemExit
                    _current_task = None
                    # 旧任务被打断，通知前端关闭遮罩
                    await websocket.send(json.dumps({
                        "type": "event",
                        "event": {"type": "activity_status", "data": {"status": "done"}},
                    }))
                agent.reset_context()
                log.info("已新建会话，上下文已重置")

            elif msg_type == "stop":
                if _current_task and not _current_task.done():
                    _current_task.cancel()
                    _current_task = None
                    log.info("用户取消 Agent 任务")
                    await websocket.send(json.dumps({"type": "stream", "content": "[DONE]"}))
                    await websocket.send(json.dumps({
                        "type": "event",
                        "event": {"type": "activity_status", "data": {"status": "done"}},
                    }))
                else:
                    log.debug("收到 stop 但无运行中的任务")

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
                # 停止采集，但保留 session 在内存，等待用户确认是否蒸馏
                trace_id = msg.get("trace_id")
                session = _record_sessions.get(trace_id)
                if session is None:
                    await websocket.send(json.dumps({
                        "type": "record_error",
                        "trace_id": trace_id,
                        "stage": "stop",
                        "message": "录制会话不存在",
                    }))
                    continue
                # 更新 label（停止确认时用户可填技能名）
                session["label"] = msg.get("label") or session.get("label", "")
                # 统计摘要供前端展示
                events = session["events"]
                domains = sorted({
                    e.get("url", "") and registered_domain_from_url(e["url"])
                    for e in events if e.get("url")
                } - {""})
                await websocket.send(json.dumps({
                    "type": "record_stopped",
                    "trace_id": trace_id,
                    "event_count": len(events),
                    "domains": domains,
                    "duration_ms": _events_duration_ms(events),
                }))
                log.info("录制停止: trace_id=%s events=%d", trace_id, len(events))

            elif msg_type == "record_distill":
                # 用户确认保存 → 触发蒸馏（从内存 session 取事件）
                trace_id = msg.get("trace_id")
                session = _record_sessions.pop(trace_id, None)
                if session is None:
                    await websocket.send(json.dumps({
                        "type": "record_error",
                        "trace_id": trace_id,
                        "stage": "distill",
                        "message": "录制会话不存在或已处理",
                    }))
                    continue
                label = msg.get("label") or session.get("label", "")
                asyncio.create_task(_run_distill(
                    websocket, agent, trace_id, session["events"], label, config,
                ))

            elif msg_type == "record_discard":
                # 用户选择丢弃 → 删除内存 session，不蒸馏
                trace_id = msg.get("trace_id")
                _record_sessions.pop(trace_id, None)
                log.info("录制已丢弃: trace_id=%s", trace_id)

            elif msg_type == "record_redistill":
                # 从 _source_trace.json 重蒸馏（失败后重试用）
                trace_id = msg.get("trace_id")
                asyncio.create_task(_redistill_from_trace(websocket, agent, trace_id, config))

    except websockets.ConnectionClosed:
        log.info("客户端断开连接，清理挂起的工具请求")
        agent.conn.disconnect()


def registered_domain_from_url(url: str) -> str:
    """从 URL 提取 eTLD+1 风格域名（简单启发式，供摘要用）。"""
    try:
        hostname = url.split("//")[-1].split("/")[0].split("?")[0]
        hostname = hostname.lstrip("www.")
        parts = hostname.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else hostname
    except Exception:
        return ""


def _events_duration_ms(events: list[dict]) -> int:
    """计算事件序列的时长（首末 timestamp 差），单位毫秒。"""
    timestamps = [int(e.get("timestamp", 0)) for e in events if e.get("timestamp") is not None]
    if len(timestamps) < 2:
        return 0
    return max(0, max(timestamps) - min(timestamps))


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


async def main():
    """启动 WebSocket 服务器。"""
    config = load_config()
    setup_logging(config)

    host = config.get("server", {}).get("host", "localhost")
    port = config.get("server", {}).get("port", "8765")

    log.info("启动 Browser Use Agent 服务器 ws://%s:%s", host, port)

    async with websockets.serve(
        lambda ws: handle_client(ws, config),
        host,
        port,
        max_size=16 * 1024 * 1024,  # 16MB，支持高 DPI 全屏截图(base64)回传，默认 1MB 会被 websockets 关闭连接
    ):
        await asyncio.Future()  # 永久运行


if __name__ == "__main__":
    asyncio.run(main())
