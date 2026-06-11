import { ArrowLeft, RotateCcw, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { EventCard } from '@/components/EventCards'
import { deleteSession, getSession } from '@/lib/idb'
import type { Session } from '@/types'

export function HistoryDetail({
  sessionId,
  onBack,
  onRerun,
}: {
  sessionId: string
  onBack: () => void
  onRerun: (task: string) => void
}) {
  const [session, setSession] = useState<Session | null>(null)

  useEffect(() => {
    getSession(sessionId).then((s) => setSession(s ?? null))
  }, [sessionId])

  if (!session) {
    return (
      <div className="flex items-center justify-center h-full text-xs text-muted-foreground">
        加载中...
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-background">
      <header className="flex items-center gap-2 border-b px-3 py-2">
        <Button variant="ghost" size="icon-sm" onClick={onBack} className="cursor-pointer" title="返回">
          <ArrowLeft className="size-3.5" />
        </Button>
        <span className="text-sm font-medium truncate">历史记录</span>
      </header>

      <div className="border-b px-3 py-2 bg-muted/30">
        <div className="text-[10px] text-muted-foreground uppercase tracking-wide">任务</div>
        <div className="text-xs font-medium" title={session.task}>{session.task}</div>
        <div className="mt-2 flex items-center gap-2">
          <button
            type="button"
            onClick={() => onRerun(session.task)}
            className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          >
            <RotateCcw className="size-3" />重新运行
          </button>
          <button
            type="button"
            onClick={async () => { await deleteSession(sessionId); onBack() }}
            className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-destructive transition-colors cursor-pointer"
          >
            <Trash2 className="size-3" />删除
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {session.messages.map((msg) => (
          <div key={msg.id} className="text-xs">
            <span className="text-muted-foreground">{msg.role === 'user' ? '用户' : msg.role === 'agent' ? 'Agent' : '系统'}:</span>
            <span className="ml-1">{msg.content}</span>
          </div>
        ))}
        {session.events.map((ev, i) => (
          <EventCard key={i} event={ev} />
        ))}
      </div>
    </div>
  )
}
