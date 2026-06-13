import { useCallback, useEffect, useRef, useState } from 'react'
import type { AgentEvent, ActivityStatus, BackgroundMessage, Message } from '@/types'

export interface UseWebSocketReturn {
  status: 'connected' | 'disconnected'
  sendTask: (content: string) => void
  messages: Message[]
  isStreaming: boolean
  stopStream: () => void
  error: string | null
  clearMessages: () => void
  activityStatus: ActivityStatus
}

function uid(): string {
  return crypto.randomUUID()
}

export function useWebSocket(): UseWebSocketReturn {
  const [status, setStatus] = useState<'connected' | 'disconnected'>('disconnected')
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activityStatus, setActivityStatus] = useState<ActivityStatus>('idle')

  const streamingRef = useRef<Message | null>(null)

  // 定时轮询连接状态
  useEffect(() => {
    const poll = () => {
      chrome.runtime.sendMessage({ type: 'get_status' }, (res) => {
        if (chrome.runtime.lastError || !res) {
          setStatus('disconnected')
        } else {
          setStatus(res.connected ? 'connected' : 'disconnected')
        }
      })
    }
    poll()
    const timer = setInterval(poll, 3000)
    return () => clearInterval(timer)
  }, [])

  // 监听 background 推送的消息
  useEffect(() => {
    const listener = (message: BackgroundMessage) => {
      if (message.type === 'stream') {
        const content = message.content ?? ''

        if (content === '[DONE]') {
          const streaming = streamingRef.current
          if (streaming) {
            streaming.status = 'done'
            streamingRef.current = null
            setIsStreaming(false)
            setActivityStatus('idle')
            setMessages((prev) => {
              // 移除之前的临时流式消息，加入最终版本
              const without = prev.filter((m) => m.id !== streaming.id)
              return [...without, { ...streaming }]
            })
          }
          return
        }

        if (content === '[BUSY]') {
          setMessages((prev) => [
            ...prev,
            { id: uid(), role: 'system', content: 'Agent 正在工作中，请等待...', timestamp: Date.now() },
          ])
          return
        }

        // 流式追加
        setIsStreaming(true)
        let streaming = streamingRef.current
        if (!streaming) {
          streaming = {
            id: uid(),
            role: 'agent',
            content,
            timestamp: Date.now(),
            status: 'streaming',
          }
          streamingRef.current = streaming
        } else {
          streaming.content += content
        }
        // 快照当前 streaming，避免闭包问题
        const snapshot = { ...streaming }
        setMessages((prev) => {
          const without = prev.filter((m) => m.id !== snapshot.id)
          return [...without, snapshot]
        })
      }

      if (message.type === 'error') {
        setError(message.error ?? '未知错误')
        streamingRef.current = null
        setIsStreaming(false)
        setMessages((prev) => [
          ...prev,
          { id: uid(), role: 'system', content: `错误：${message.error ?? '未知错误'}`, timestamp: Date.now() },
        ])
      }

      if (message.type === 'status_update') {
        setStatus(message.status ?? 'disconnected')
      }

      if (message.type === 'event') {
        const evt = message.event
        if (!evt) return

        if (evt.type === 'activity_status') {
          setActivityStatus(evt.data?.status as ActivityStatus)
          return
        }

        // 确保有 streaming 消息承载事件：模型可能直接调用工具（无文本输出），
        // 此时首个 stream delta 尚未到达，需先创建承载消息，否则 step/reflection 事件被丢弃。
        let streaming = streamingRef.current
        if (!streaming) {
          streaming = {
            id: uid(),
            role: 'agent',
            content: '',
            timestamp: Date.now(),
            status: 'streaming',
          }
          streamingRef.current = streaming
          setIsStreaming(true)
        }
        streaming.events = [...(streaming.events ?? []), evt]
        // 触发重渲染：工具步骤需随事件实时刷新，而非等下一个 stream delta。
        const snapshot = { ...streaming }
        setMessages((prev) => {
          const without = prev.filter((m) => m.id !== snapshot.id)
          return [...without, snapshot]
        })
      }
    }

    chrome.runtime.onMessage.addListener(listener)
    return () => chrome.runtime.onMessage.removeListener(listener)
  }, [])

  const sendTask = useCallback((content: string) => {
    const userMsg: Message = {
      id: uid(),
      role: 'user',
      content,
      timestamp: Date.now(),
    }
    setMessages((prev) => [...prev, userMsg])
    setError(null)
    setActivityStatus('idle')
    chrome.runtime.sendMessage({ type: 'user_message', content })
  }, [])

  const stopStream = useCallback(() => {
    const streaming = streamingRef.current
    if (streaming) {
      streaming.status = 'done'
      streamingRef.current = null
      setMessages((prev) => {
        const without = prev.filter((m) => m.id !== streaming.id)
        return [...without, { ...streaming }]
      })
    }
    setIsStreaming(false)
    setActivityStatus('idle')
    // 通知 background 停止后端 agent
    chrome.runtime.sendMessage({ type: 'stop' })
  }, [])

const clearMessages = useCallback(() => {
    setMessages([])
    streamingRef.current = null
    setIsStreaming(false)
    setError(null)
  }, [])

  return { status, sendTask, messages, isStreaming, stopStream, error, clearMessages, activityStatus }
}
