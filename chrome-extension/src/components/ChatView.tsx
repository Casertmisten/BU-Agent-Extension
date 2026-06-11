import { Send, Square } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { Message } from '@/types'
import { ActivityCard, EventCard } from '@/components/EventCards'
import { EmptyState } from '@/components/misc'
import { Button } from '@/components/ui/button'
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from '@/components/ui/input-group'

interface ChatViewProps {
  messages: Message[]
  isStreaming: boolean
  sendTask: (content: string) => void
  stopStream: () => void
}

export function ChatView({ messages, isStreaming, sendTask, stopStream }: ChatViewProps) {
  const [inputValue, setInputValue] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, isStreaming])

  const handleSubmit = useCallback(() => {
    const text = inputValue.trim()
    if (!text || isStreaming) return
    sendTask(text)
    setInputValue('')
  }, [inputValue, isStreaming, sendTask])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const showEmpty = messages.length === 0 && !isStreaming

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* 消息列表 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-2">
        {showEmpty && <EmptyState />}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {isStreaming && <ActivityCard />}
      </div>

      {/* 输入区域 */}
      <footer className="border-t p-3">
        <InputGroup className="relative rounded-lg">
          <InputGroupTextarea
            ref={textareaRef}
            placeholder="输入任务... (Enter 发送)"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isStreaming}
            className="text-xs pr-12 min-h-10"
          />
          <InputGroupAddon align="inline-end" className="absolute bottom-0 right-0">
            {isStreaming ? (
              <InputGroupButton
                size="icon-sm"
                variant="destructive"
                onClick={stopStream}
                className="size-7 cursor-pointer"
                title="停止"
              >
                <Square className="size-3" />
              </InputGroupButton>
            ) : (
              <InputGroupButton
                size="icon-sm"
                variant="default"
                onClick={handleSubmit}
                disabled={!inputValue.trim()}
                className="size-7 cursor-pointer"
                title="发送"
              >
                <Send className="size-3" />
              </InputGroupButton>
            )}
          </InputGroupAddon>
        </InputGroup>
      </footer>
    </div>
  )
}

// --- 消息气泡 ---
function MessageBubble({ message }: { message: Message }) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-xl rounded-br-sm bg-gradient-to-br from-emerald-500 to-emerald-600 text-white px-3 py-2 text-xs whitespace-pre-wrap shadow-sm">
          {message.content}
        </div>
      </div>
    )
  }

  if (message.role === 'system') {
    return (
      <div className="text-center text-[11px] text-muted-foreground py-1">{message.content}</div>
    )
  }

  // agent 消息
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-xl rounded-bl-sm border bg-card px-3 py-2 text-xs whitespace-pre-wrap shadow-sm">
        {message.content}
        {message.events && message.events.length > 0 && (
          <div className="mt-2 space-y-2">
            {message.events.map((ev, i) => (
              <EventCard key={i} event={ev} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
