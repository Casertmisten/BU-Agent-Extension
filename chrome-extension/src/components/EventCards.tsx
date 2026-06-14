import {
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Globe,
  Keyboard,
  Loader2,
  Mouse,
  MoveVertical,
  RefreshCw,
  Search,
  Sparkles,
  XCircle,
  Zap,
} from 'lucide-react'
import { useState, Fragment } from 'react'
import type { AgentEvent, ActivityStatus } from '@/types'
import { cn } from '@/lib/utils'

// --- 工具图标映射 ---
function ToolIcon({ name, className }: { name: string; className?: string }) {
  const icons: Record<string, React.ReactNode> = {
    click_element: <Mouse className={className} />,
    input_text: <Keyboard className={className} />,
    scroll_page: <MoveVertical className={className} />,
    navigate: <Globe className={className} />,
    parse_dom: <Search className={className} />,
    parse_page: <Search className={className} />,
    screenshot_analyze: <Search className={className} />,
    get_element_info: <Search className={className} />,
    cdp_click: <Mouse className={className} />,
    wait: <RefreshCw className={className} />,
    done: <CheckCircle className={className} />,
    extract_content: <Search className={className} />,
    go_back: <Globe className={className} />,
    scroll_element: <MoveVertical className={className} />,
  }
  return icons[name] || <Zap className={className} />
}

// --- 工具名称友好显示 ---
function toolDisplayName(name: string): string {
  const map: Record<string, string> = {
    click_element: '点击元素',
    input_text: '输入文本',
    scroll_page: '滚动页面',
    navigate: '导航',
    parse_dom: '解析页面',
    parse_page: '解析页面结构',
    screenshot_analyze: '截图分析',
    get_element_info: '获取元素信息',
    cdp_click: '坐标点击',
    wait: '等待',
    done: '完成任务',
    extract_content: '提取内容',
    go_back: '后退',
    scroll_element: '滚动元素',
  }
  return map[name] || name
}

// --- 格式化工具参数为简短摘要 ---
function formatInputSummary(input: unknown): string {
  if (!input || (typeof input === 'object' && Object.keys(input as object).length === 0)) return ''
  if (typeof input === 'string') return input.length > 60 ? input.slice(0, 60) + '...' : input
  const obj = input as Record<string, unknown>
  // 取第一个有意义的值做摘要
  const entries = Object.entries(obj)
  if (entries.length === 0) return ''
  const [key, val] = entries[0]
  const valStr = String(val)
  return `${key}: ${valStr.length > 40 ? valStr.slice(0, 40) + '...' : valStr}`
}

// --- 思考过程单项 ---
function ReflectionItem({ icon, value }: { icon: string; value: string }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <>
      <span className="text-xs flex justify-center">{icon}</span>
      <span
        className={cn(
          'text-[11px] text-muted-foreground cursor-pointer hover:text-muted-foreground/70',
          !expanded && 'line-clamp-1'
        )}
        onClick={() => setExpanded(!expanded)}
      >
        {value}
      </span>
    </>
  )
}

// --- 思考过程展示 ---
function ReflectionSection({ data }: { data: { evaluation_previous_goal?: string; memory?: string; next_goal?: string } }) {
  const items = [
    { icon: '☑️', value: data.evaluation_previous_goal },
    { icon: '🧠', value: data.memory },
    { icon: '🎯', value: data.next_goal },
  ].filter(item => item.value)

  if (items.length === 0) return null

  return (
    <div className="mb-2 bg-muted/30 rounded p-1.5">
      <div className="grid grid-cols-[14px_1fr] gap-x-2 gap-y-1.5">
        {items.map(item => (
          <ReflectionItem key={item.icon} icon={item.icon} value={item.value!} />
        ))}
      </div>
    </div>
  )
}

// --- 调试面板 ---
function RawSection({ input, output }: { input?: unknown; output?: unknown }) {
  const [activeTab, setActiveTab] = useState<'request' | 'response' | null>(null)

  if (!input && !output) return null

  const content = activeTab === 'request' ? input : activeTab === 'response' ? output : null

  return (
    <div className="mt-2 border-t border-dashed pt-2">
      <div className="flex items-center gap-3">
        {input != null && (
          <button type="button" onClick={() => setActiveTab(activeTab === 'request' ? null : 'request')}
            className={cn('text-[10px] transition-colors border-b cursor-pointer',
              activeTab === 'request' ? 'text-foreground border-foreground' : 'text-muted-foreground border-transparent hover:text-foreground')}>
            Request
          </button>
        )}
        {output != null && (
          <button type="button" onClick={() => setActiveTab(activeTab === 'response' ? null : 'response')}
            className={cn('text-[10px] transition-colors border-b cursor-pointer',
              activeTab === 'response' ? 'text-foreground border-foreground' : 'text-muted-foreground border-transparent hover:text-foreground')}>
            Response
          </button>
        )}
      </div>
      {content != null && (
        <div className="relative mt-1.5">
          <button type="button" onClick={() => { navigator.clipboard.writeText(JSON.stringify(content, null, 2)) }}
            className="absolute top-1 right-1 text-[9px] text-muted-foreground hover:text-foreground border px-1 rounded cursor-pointer">
            Copy
          </button>
          <pre className="p-2 pt-5 text-[10px] text-foreground/70 bg-muted rounded overflow-x-auto max-h-60 overflow-y-auto">
            {JSON.stringify(content, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

// --- 单个工具调用步骤 ---
function StepCard({ event, stepNumber, reflection, completed }: { event: AgentEvent; stepNumber: number; reflection?: { evaluation_previous_goal?: string; memory?: string; next_goal?: string }; completed?: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const data = event.data
  const status = (data.status as string) || 'done'
  const action = (data.action as string) || ''
  const isRunning = !completed && status === 'running'
  const input = data.input
  const output = data.output as string | undefined

  const StatusIcon = isRunning
    ? () => <Loader2 className="size-3 text-blue-500 animate-spin" />
    : status === 'error'
      ? () => <XCircle className="size-3 text-destructive" />
      : () => <CheckCircle className="size-3 text-green-500" />

  return (
    <div className="rounded-lg border-l-2 border-l-blue-500 border bg-muted/40 p-2.5">
      <div className="flex items-center gap-1.5">
        <ToolIcon name={action} className="size-3.5 text-blue-500 shrink-0" />
        <span className="text-[11px] font-semibold text-foreground">
          #{stepNumber} {toolDisplayName(action)}
        </span>
        <StatusIcon />
        {!isRunning && (input || output) && (
          <button type="button" onClick={() => setExpanded(!expanded)}
            className="text-muted-foreground hover:text-foreground cursor-pointer ml-auto shrink-0">
            {expanded ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
          </button>
        )}
      </div>

      {reflection && <ReflectionSection data={reflection} />}

      {isRunning && <p className="text-[10px] text-muted-foreground mt-0.5">执行中...</p>}

      {!isRunning && !expanded && !!input && (
        <p className="text-[10px] text-muted-foreground/70 mt-0.5 truncate">{formatInputSummary(input)}</p>
      )}

      {expanded && (
        <div className="mt-1 space-y-0.5">
          {!!input && (
            <p className="text-[10px] text-muted-foreground/70">
              <span className="text-muted-foreground font-medium">参数: </span>
              <span className="break-all">{typeof input === 'string' ? input : JSON.stringify(input)}</span>
            </p>
          )}
          {output && (
            <p className="text-[10px] text-muted-foreground/70">
              <span className="text-muted-foreground font-medium">结果: </span>
              <span className="break-all">{String(output)}</span>
            </p>
          )}
          <RawSection input={input} output={output} />
        </div>
      )}
    </div>
  )
}

// --- 多状态 ActivityCard ---
export function ActivityCard({ status }: { status: ActivityStatus }) {
  if (status === 'idle') return null

  const config: Record<string, { icon: React.ReactNode; text: string; color: string; ping: string }> = {
    thinking: { icon: <Sparkles className="size-3.5" />, text: 'Agent 正在思考...', color: 'text-blue-500', ping: 'bg-blue-500' },
    executing: { icon: <Sparkles className="size-3.5" />, text: 'Agent 正在执行操作...', color: 'text-blue-500', ping: 'bg-blue-500' },
    retrying: { icon: <RefreshCw className="size-3.5" />, text: '重试中...', color: 'text-amber-500', ping: 'bg-amber-500' },
    error: { icon: <XCircle className="size-3.5" />, text: '出错了', color: 'text-destructive', ping: 'bg-destructive' },
    done: { icon: <CheckCircle className="size-3.5" />, text: '完成', color: 'text-green-500', ping: 'bg-green-500' },
  }

  const info = config[status]
  if (!info) return null

  return (
    <div className="flex items-center gap-2 rounded-lg border bg-muted/40 p-2.5 animate-pulse">
      <div className="relative">
        <span className={info.color}>{info.icon}</span>
        <span className={cn('absolute -top-0.5 -right-0.5 size-1.5 rounded-full animate-ping', info.ping)} />
      </div>
      <span className={cn('text-xs', info.color)}>{info.text}</span>
    </div>
  )
}

// 合并同一工具调用的 running + done 事件为一条
function mergeStepEvents(events: AgentEvent[]): AgentEvent[] {
  const result: AgentEvent[] = []
  const pending = new Map<string, number>()
  for (const event of events) {
    if (event.type !== "step") { result.push(event); continue }
    const action = (event.data.action as string) || ""
    const status = (event.data.status as string) || "done"
    if (status === "running") {
      result.push(event)
      pending.set(action, result.length - 1)
    } else {
      const idx = pending.get(action)
      if (idx !== undefined) {
        result[idx] = { ...result[idx], data: { ...result[idx].data, ...event.data } }
        pending.delete(action)
      } else {
        result.push(event)
      }
    }
  }
  return result
}

// --- 事件流容器 ---
export function EventStream({ events, completed }: { events: AgentEvent[]; completed?: boolean }) {
  const visible = mergeStepEvents(events.filter(e => e.type !== 'activity_status'))
  if (visible.length === 0) return null

  let stepCount = 0
  let pendingReflection: { evaluation_previous_goal?: string; memory?: string; next_goal?: string } | undefined

  return (
    <div className="mt-2 space-y-1.5">
      {visible.map((event, i) => {
        if (event.type === 'reflection') {
          pendingReflection = event.data as { evaluation_previous_goal?: string; memory?: string; next_goal?: string }
          return null
        }
        if (event.type === 'step') {
          stepCount++
          const reflection = pendingReflection
          pendingReflection = undefined
          return <StepCard key={i} event={event} stepNumber={stepCount} reflection={reflection} completed={completed} />
        }
        if (event.type === 'error') {
          return (
            <div key={i} className="rounded-lg border border-destructive/30 bg-destructive/10 p-2.5">
              <div className="flex items-start gap-1.5">
                <XCircle className="size-3 text-destructive shrink-0 mt-0.5" />
                <span className="text-xs text-destructive">{(event.data.message as string) || '未知错误'}</span>
              </div>
            </div>
          )
        }
        if (event.type === 'retry') {
          return (
            <div key={i} className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5">
              <div className="flex items-start gap-1.5">
                <RefreshCw className="size-3 text-amber-500 shrink-0 mt-0.5" />
                <span className="text-xs text-amber-600 dark:text-amber-400">{(event.data.message as string) || '重试中...'}</span>
              </div>
            </div>
          )
        }
        return null
      })}
    </div>
  )
}

// --- 思考指示器 ---
export function ThinkingIndicator() {
  return (
    <div className="flex items-center gap-2 px-1 py-1.5 shrink-0">
      <div className="relative flex items-center justify-center">
        <Sparkles className="size-3.5 text-blue-500" />
        <span className="absolute -top-0.5 -right-0.5 size-1.5 rounded-full bg-blue-500 animate-ping" />
      </div>
      <span className="text-xs text-blue-500 font-medium">Agent 正在深度思考...</span>
    </div>
  )
}

// --- 工具步骤折叠面板 ---
export function ToolStepsPanel({ events, isStreaming }: { events: AgentEvent[]; isStreaming?: boolean }) {
  const [collapsed, setCollapsed] = useState(true)
  const visible = mergeStepEvents(events.filter(e => e.type !== 'activity_status'))
  const steps = visible.filter(e => e.type === 'step')

  // 当前运行的步骤；没有则取最后一个已完成步骤
  const runningStep = steps.find(e => e.data.status === 'running')
  const lastStep = runningStep || steps[steps.length - 1]
  const currentStepName = lastStep
    ? toolDisplayName((lastStep.data.action as string) || '')
    : isStreaming ? '思考中...' : ''

  if (visible.length === 0) return null

  return (
    <div className="rounded-lg border bg-muted/30 overflow-hidden shrink-0">
      <div
        className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-muted/50 transition-colors"
        onClick={() => setCollapsed(!collapsed)}
      >
        <div className="flex items-center gap-1.5">
          {collapsed
            ? <ChevronRight className="size-3.5 text-muted-foreground" />
            : <ChevronDown className="size-3.5 text-muted-foreground" />}
          <span className="text-xs font-medium text-foreground">工具调用步骤 ({steps.length})</span>
        </div>
        {currentStepName && (
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-blue-500 font-medium">{currentStepName}</span>
            {isStreaming
              ? <Loader2 className="size-3.5 text-blue-500 animate-spin" />
              : <CheckCircle className="size-3.5 text-green-500" />}
          </div>
        )}
      </div>
      {!collapsed && (
        <div className="px-2 pb-2">
          <EventStream events={events} completed={!isStreaming} />
        </div>
      )}
    </div>
  )
}


// --- 向后兼容的 EventCard ---
export function EventCard({ event }: { event: AgentEvent }) {
  return <EventStream events={[event]} />
}

// --- 向后兼容的 ToolCallTimeline（委托给 EventStream）---
export function ToolCallTimeline({ events }: { events: AgentEvent[] }) {
  return <EventStream events={events} />
}
