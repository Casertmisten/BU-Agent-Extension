import {
  CheckCircle,
  Eye,
  Globe,
  Keyboard,
  Mouse,
  MoveVertical,
  RefreshCw,
  Sparkles,
  XCircle,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import type { AgentEvent } from '@/types'
import { cn } from '@/lib/utils'

// --- 结果卡片 ---
function ResultCard({ success, text }: { success: boolean; text: string }) {
  return (
    <div className={cn('rounded-lg border p-3', success ? 'border-green-500/30 bg-green-500/10' : 'border-destructive/30 bg-destructive/10')}>
      <div className="flex items-center gap-2 mb-1">
        {success ? <CheckCircle className="size-3.5 text-green-500" /> : <XCircle className="size-3.5 text-destructive" />}
        <span className={cn('text-xs font-medium', success ? 'text-green-600 dark:text-green-400' : 'text-destructive')}>
          结果: {success ? '成功' : '失败'}
        </span>
      </div>
      <p className="text-[12px] text-foreground pl-5 whitespace-pre-wrap">{text}</p>
    </div>
  )
}

// --- 调试原始数据折叠区 ---
function RawSection({ data }: { data?: Record<string, unknown> }) {
  const [open, setOpen] = useState(false)
  if (!data) return null
  return (
    <div className="mt-2 border-t border-dashed pt-2">
      <button type="button" onClick={() => setOpen(!open)} className="text-[10px] text-muted-foreground hover:text-foreground cursor-pointer">
        {open ? '收起原始数据' : '展开原始数据'}
      </button>
      {open && (
        <pre className="mt-1 p-2 text-[10px] text-foreground/70 bg-muted rounded overflow-x-auto max-h-40 overflow-y-auto">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  )
}

// --- 步骤图标 ---
function ActionIcon({ name, className }: { name: string; className?: string }) {
  const icons: Record<string, React.ReactNode> = {
    click: <Mouse className={className} />,
    input_text: <Keyboard className={className} />,
    scroll: <MoveVertical className={className} />,
    navigate: <Globe className={className} />,
  }
  return icons[name] || <Zap className={className} />
}

// --- StepCard ---
function StepCard({ event }: { event: AgentEvent }) {
  const { data } = event
  return (
    <div className="rounded-lg border-l-2 border-l-blue-500/50 border bg-muted/40 p-2.5">
      {data.step && <div className="text-[11px] font-semibold text-foreground tracking-wide mb-1">Step #{data.step}</div>}
      {data.action && (
        <div className="flex items-start gap-2">
          <ActionIcon name={(data.action as string)} className="size-3.5 text-blue-500 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-xs text-foreground/80">
              <span className="font-medium text-foreground/70">{data.action as string}</span>
              {data.input && <span className="text-muted-foreground/70 ml-1.5">{JSON.stringify(data.input)}</span>}
            </p>
            {data.output && (
              <p className="text-[11px] text-muted-foreground/70">{data.output as string}</p>
            )}
          </div>
        </div>
      )}
      <RawSection data={data.raw as Record<string, unknown> | undefined} />
    </div>
  )
}

// --- ObservationCard ---
function ObservationCard({ event }: { event: AgentEvent }) {
  return (
    <div className="rounded-lg border-l-2 border-l-green-500/50 border bg-muted/40 p-2.5">
      <div className="flex items-start gap-2">
        <Eye className="size-3.5 text-green-500 shrink-0 mt-0.5" />
        <span className="text-[11px] text-muted-foreground">{(event.data.content as string) || '观察'}</span>
      </div>
    </div>
  )
}

// --- ErrorCard ---
function ErrorCard({ event }: { event: AgentEvent }) {
  return (
    <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-2.5">
      <div className="flex items-start gap-1.5">
        <XCircle className="size-3 text-destructive shrink-0 mt-0.5" />
        <span className="text-xs text-destructive">{(event.data.message as string) || '未知错误'}</span>
      </div>
    </div>
  )
}

// --- RetryCard ---
function RetryCard({ event }: { event: AgentEvent }) {
  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5">
      <div className="flex items-start gap-1.5">
        <RefreshCw className="size-3 text-amber-500 shrink-0 mt-0.5" />
        <span className="text-xs text-amber-600 dark:text-amber-400">
          {(event.data.message as string) || '重试中...'}
        </span>
      </div>
    </div>
  )
}

// --- ActivityCard ---
export function ActivityCard() {
  return (
    <div className="flex items-center gap-2 rounded-lg border bg-muted/40 p-2.5 animate-pulse">
      <div className="relative">
        <Sparkles className="size-3.5 text-blue-500" />
        <span className="absolute -top-0.5 -right-0.5 size-1.5 rounded-full animate-ping bg-blue-500" />
      </div>
      <span className="text-xs text-blue-500">Agent 正在处理...</span>
    </div>
  )
}

// --- 统一事件卡片分发 ---
export function EventCard({ event }: { event: AgentEvent }) {
  // done 动作 → 结果卡片
  if (event.type === 'result') {
    return <ResultCard success={event.data.success !== false} text={(event.data.text as string) || ''} />
  }
  if (event.type === 'step') return <StepCard event={event} />
  if (event.type === 'observation') return <ObservationCard event={event} />
  if (event.type === 'error') return <ErrorCard event={event} />
  if (event.type === 'retry') return <RetryCard event={event} />
  return null
}
