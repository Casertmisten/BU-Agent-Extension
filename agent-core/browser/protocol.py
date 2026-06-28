# browser/protocol.py
"""WebSocket 消息协议：类型常量和验证。"""

MSG_TYPES = frozenset({
    "action",        # Agent → 扩展：工具指令
    "result",        # 扩展 → Agent：工具执行结果
    "heartbeat",     # 双向：保活
    "page_ready",    # 扩展 → Agent：页面导航完成
    "stream",        # Agent → 扩展：Agent 文本回复
    "mode_change",   # SidePanel → 扩展：AI/人工模式切换
    "user_message",  # SidePanel → Agent：用户聊天输入
    "stop",          # SidePanel → Agent：取消当前任务
    "new_session",   # SidePanel → Agent：新建会话，重置上下文
    "browser_state", # 扩展 → Agent：浏览器状态快照（标签页、URL、可交互元素）
    "tab_change",    # 扩展 → Agent：标签页变化通知
    # 录制功能（SidePanel → 后端）
    "record_start",      # 开始录制
    "record_event",      # 批量上传录制事件
    "record_stop",       # 停止采集（保留 session，不蒸馏）
    "record_distill",    # 用户确认保存 → 触发蒸馏
    "record_discard",    # 用户选择丢弃 → 删除 session
    "record_redistill",  # 从 trace 重蒸馏（失败重试）
    "get_status",        # 查询连接状态
    "get_skills",        # 拉取技能清单
})


def validate_message(msg: dict) -> bool:
    """验证消息字典是否包含已知的 type 字段。

    有效返回 True，否则抛出 ValueError。
    """
    msg_type = msg.get("type")
    if msg_type is None:
        raise ValueError("Missing 'type' field in message")
    if msg_type not in MSG_TYPES:
        raise ValueError(f"Unknown message type: {msg_type}")
    return True
