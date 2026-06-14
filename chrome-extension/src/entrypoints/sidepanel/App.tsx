import { Plus } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { View, AppConfig } from '@/types'
import { ChatView } from '@/components/ChatView'
import { ConfigPanel } from '@/components/ConfigPanel'
import { HistoryDetail } from '@/components/HistoryDetail'
import { HistoryList } from '@/components/HistoryList'
import { NavButtons, StatusDot } from '@/components/misc'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useConfig } from '@/hooks/useConfig'
import { saveSession } from '@/lib/idb'

export default function App() {
  const [view, setView] = useState<View>({ name: 'chat' })
  const { status, sendTask, messages, isStreaming, stopStream, clearMessages, activityStatus, skills } = useWebSocket()
  const { config, saveConfig } = useConfig()
  const prevStreamingRef = useRef(isStreaming)

  // 会话持久化：流结束时保存
  useEffect(() => {
    const wasStreaming = prevStreamingRef.current
    prevStreamingRef.current = isStreaming
    if (wasStreaming && !isStreaming && messages.length > 0) {
      const task = messages.find((m) => m.role === 'user')?.content || ''
      const events = messages.flatMap((m) => m.events ?? [])
      const lastMsg = messages[messages.length - 1]
      const sessionStatus = lastMsg.role === 'system' && lastMsg.content.startsWith('错误') ? 'error' : 'completed'
      saveSession({ task, messages, events, status: sessionStatus }).catch((err) =>
        console.error('[App] 保存会话失败:', err)
      )
    }
  }, [isStreaming, messages])

  const handleRerun = useCallback((task: string) => {
    setView({ name: 'chat' })
    sendTask(task)
  }, [sendTask])

  const handleSaveConfig = useCallback((newConfig: AppConfig) => {
    saveConfig(newConfig)
    setView({ name: 'chat' })
  }, [saveConfig])

  // --- 视图路由 ---
  if (view.name === 'config') {
    return (
      <div className="flex flex-col h-screen bg-background">
        <ConfigPanel config={config} onSave={handleSaveConfig} onClose={() => setView({ name: 'chat' })} />
      </div>
    )
  }

  if (view.name === 'history') {
    return (
      <div className="flex flex-col h-screen bg-background">
        <HistoryList
          onSelect={(id) => setView({ name: 'history-detail', sessionId: id })}
          onBack={() => setView({ name: 'chat' })}
          onRerun={handleRerun}
        />
      </div>
    )
  }

  if (view.name === 'history-detail') {
    return (
      <div className="flex flex-col h-screen bg-background">
        <HistoryDetail
          sessionId={view.sessionId}
          onBack={() => setView({ name: 'history' })}
          onRerun={handleRerun}
        />
      </div>
    )
  }

  // --- 聊天主视图 ---
  return (
    <div className="flex flex-col h-screen bg-background">
      <header className="flex items-center justify-between border-b px-3 py-2">
        <button
          onClick={clearMessages}
          className="size-7 flex items-center justify-center rounded-full border border-input text-muted-foreground hover:bg-muted hover:text-foreground transition-colors cursor-pointer"
          title="新建会话"
        >
          <Plus className="size-4" />
        </button>
        <div className="flex items-center">
          <StatusDot status={status === 'connected' ? (isStreaming ? 'running' : 'connected') : 'disconnected'} />
          <NavButtons onHistory={() => setView({ name: 'history' })} onSettings={() => setView({ name: 'config' })} />
        </div>
      </header>


      <ChatView messages={messages} isStreaming={isStreaming} sendTask={sendTask} stopStream={stopStream} activityStatus={activityStatus} skills={skills} />

      <footer className="text-center py-1.5 text-[11px] text-muted-foreground border-t">
        版本 v0.2.0
      </footer>
    </div>
  )
}
