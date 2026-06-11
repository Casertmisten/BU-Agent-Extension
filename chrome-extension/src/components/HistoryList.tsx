import { ArrowLeft, CheckCircle, History, RotateCcw, Trash2, XCircle } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { deleteSession, listSessions, clearSessions } from '@/lib/idb'
import type { Session } from '@/types'

function timeAgo(ts: number): string {
  const seconds = Math.floor((Date.now() - ts) / 1000)
  if (seconds < 60) return '刚刚'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}小时前`
  const days = Math.floor(hours / 24)
  return `${days}天前`
}

export function HistoryList({
  onSelect,
  onBack,
  onRerun,
}: {
  onSelect: (id: string) => void
  onBack: () => void
  onRerun: (task: string) => void
}) {
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      setSessions(await listSessions())
    } catch (err) {
      console.error('[HistoryList] 加载失败:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    await deleteSession(id)
    setSessions((prev) => prev.filter((s) => s.id !== id))
  }

  return (
    <div className="flex flex-col h-full bg-background">
      <header className="flex items-center gap-2 border-b px-3 py-2">
        <Button variant="ghost" size="icon-sm" onClick={onBack} className="cursor-pointer" title="返回">
          <ArrowLeft className="size-3.5" />
        </Button>
        <span className="text-sm font-medium flex-1">历史记录</span>
        {sessions.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={async () => { await clearSessions(); setSessions([]) }}
            className="text-[10px] text-muted-foreground hover:text-destructive cursor-pointer h-6 px-2"
          >
            <Trash2 className="size-3 mr-1" />清空
          </Button>
        )}
      </header>

      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="flex flex-col">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="flex items-start gap-2 px-3 py-2.5 border-b">
                <div className="size-3.5 mt-0.5 rounded-full bg-muted animate-pulse shrink-0" />
                <div className="flex-1 space-y-1.5">
                  <div className="h-2.5 bg-muted animate-pulse rounded w-3/4" />
                  <div className="h-2 bg-muted animate-pulse rounded w-1/3" />
                </div>
              </div>
            ))}
          </div>
        )}

        {!loading && sessions.length === 0 && (
          <div className="flex flex-col items-center justify-center h-40 gap-2 text-muted-foreground">
            <History className="size-8 opacity-30" />
            <p className="text-xs">暂无历史记录</p>
          </div>
        )}

        {sessions.map((session) => (
          <div
            key={session.id}
            role="button"
            tabIndex={0}
            onClick={() => onSelect(session.id)}
            className="w-full text-left px-3 py-2.5 border-b hover:bg-muted/50 transition-colors cursor-pointer flex items-start gap-2 group"
          >
            {session.status === 'completed'
              ? <CheckCircle className="size-3.5 text-green-500 shrink-0 mt-0.5" />
              : <XCircle className="size-3.5 text-destructive shrink-0 mt-0.5" />}
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium truncate">{session.task}</p>
              <div className="flex items-center mt-0.5">
                <p className="text-[10px] text-muted-foreground">
                  {timeAgo(session.createdAt)} · {session.messages.length} 条消息
                </p>
                <div className="flex items-center gap-0.5 ml-auto opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); onRerun(session.task) }}
                    className="p-0.5 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                    title="重新运行"
                  >
                    <RotateCcw className="size-3" />
                  </button>
                  <button
                    type="button"
                    onClick={(e) => handleDelete(e, session.id)}
                    className="p-0.5 text-muted-foreground hover:text-destructive transition-colors cursor-pointer"
                    title="删除"
                  >
                    <Trash2 className="size-3" />
                  </button>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
