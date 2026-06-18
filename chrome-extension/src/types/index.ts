/** 侧边面板 → 后台的消息 */
export interface SidepanelMessage {
  type: 'user_message' | 'get_status' | 'get_skills' | 'stop' | 'new_session'
  content?: string
}

/** 后台 → 侧边面板的消息 */
export interface BackgroundMessage {
  type: 'stream' | 'error' | 'status_update' | 'event' | 'skills_list'
  content?: string
  status?: 'connected' | 'disconnected'
  event?: AgentEvent
  error?: string
  skills?: SkillInfo[]
}

/** 技能信息（后端推送的技能清单元素） */
export interface SkillInfo {
  name: string
  description: string
}

/** 后台 ↔ 内容脚本的消息（保持现有 content.js 格式） */
export interface ContentMessage {
  action: 'parse_page' | 'parse_dom' | 'get_element_info' | 'click' | 'input_text' | 'scroll' | 'enable_overlay' | 'disable_overlay'
  task_id?: string
  url?: string
  seconds?: number
  x?: number
  y?: number
  [key: string]: unknown
}

/** UI 层消息 */
export interface Message {
  id: string
  role: 'user' | 'agent' | 'system'
  content: string
  timestamp: number
  status?: 'streaming' | 'done' | 'error'
  events?: AgentEvent[]
}

/** Agent 事件（事件卡片用） */
export interface AgentEvent {
  type: 'step' | 'observation' | 'error' | 'result' | 'retry' | 'activity' | 'reflection' | 'activity_status' | 'token_usage'
  data: Record<string, unknown>
  timestamp: number
}

export type ActivityStatus = 'idle' | 'thinking' | 'executing' | 'retrying' | 'error' | 'done'

export interface ReflectionData {
  evaluation_previous_goal?: string
  memory?: string
  next_goal?: string
}

/** 会话（IndexedDB 持久化） */
export interface Session {
  id: string
  task: string
  messages: Message[]
  events: AgentEvent[]
  status: 'running' | 'completed' | 'error'
  createdAt: number
}

/** 应用配置 */
export interface AppConfig {
  wsUrl: string
  model: string
  token: string
}

/** 视图路由 */
export type View =
  | { name: 'chat' }
  | { name: 'config' }
  | { name: 'history' }
  | { name: 'history-detail'; sessionId: string }
