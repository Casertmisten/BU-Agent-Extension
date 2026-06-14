import { Send, Square, Sparkles } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { Message, SkillInfo } from '@/types'
import { ThinkingIndicator } from '@/components/EventCards'
import { MessageBlock } from '@/components/MessageBlock'
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
  activityStatus: string
  skills: SkillInfo[]
}

export function ChatView({ messages, isStreaming, sendTask, stopStream, activityStatus, skills }: ChatViewProps) {
  const [inputValue, setInputValue] = useState('')
  const [showSkills, setShowSkills] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const skillPopoverRef = useRef<HTMLDivElement>(null)

  // 点击 Popover 外部时关闭
  useEffect(() => {
    if (!showSkills) return
    const handler = (e: MouseEvent) => {
      if (skillPopoverRef.current && !skillPopoverRef.current.contains(e.target as Node)) {
        setShowSkills(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [showSkills])

  // 选中技能：把 /skill <name> 填入输入框（保留用户已输入内容），聚焦并把光标置于末尾
  const insertSkill = useCallback((skillName: string) => {
    const prefix = `/skill ${skillName} `
    setInputValue((prev) => {
      const trimmed = prev.trim()
      return trimmed ? `${prefix}${trimmed}` : prefix
    })
    setShowSkills(false)
    // 聚焦并移到末尾（下一帧，确保 value 已更新）
    requestAnimationFrame(() => {
      const ta = textareaRef.current
      if (ta) {
        ta.focus()
        const end = ta.value.length
        ta.setSelectionRange(end, end)
      }
    })
  }, [])

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
          <MessageBlock key={msg.id} message={msg} activityStatus={activityStatus} />
        ))}

        {/* 发送消息后等待响应时的思考指示器 */}
        {activityStatus === 'thinking' && !isStreaming && (
          <ThinkingIndicator />
        )}
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

        {/* 技能工具栏 */}
        <div ref={skillPopoverRef} className="relative mt-2">
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() => setShowSkills((v) => !v)}
            disabled={isStreaming}
            title="选择技能"
          >
            <Sparkles className="size-3.5" />
            技能
          </Button>
          {showSkills && (
            <div className="absolute bottom-full mb-2 left-0 w-72 rounded-md border bg-popover p-1 shadow-md z-10">
              {skills.length === 0 ? (
                <div className="px-3 py-2 text-xs text-muted-foreground">暂无可用技能</div>
              ) : (
                skills.map((s) => (
                  <button
                    key={s.name}
                    type="button"
                    className="block w-full text-left px-3 py-2 rounded-sm hover:bg-accent"
                    onClick={() => insertSkill(s.name)}
                  >
                    <div className="text-xs font-medium">/skill {s.name}</div>
                    <div className="text-[11px] text-muted-foreground line-clamp-1">{s.description}</div>
                  </button>
                ))
              )}
            </div>
          )}
        </div>
      </footer>
    </div>
  )
}
