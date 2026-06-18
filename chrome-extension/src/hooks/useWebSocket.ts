import { useCallback, useEffect, useRef, useState } from 'react'
import type { AgentEvent, ActivityStatus, BackgroundMessage, Message, SkillInfo } from '@/types'

export interface UseWebSocketReturn {
  status: 'connected' | 'disconnected'
  sendTask: (content: string) => void
  messages: Message[]
  isStreaming: boolean
  stopStream: () => void
  error: string | null
  clearMessages: () => void
  activityStatus: ActivityStatus
  skills: SkillInfo[]
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
  const [skills, setSkills] = useState<SkillInfo[]>([])

  const streamingRef = useRef<Message | null>(null)
  // rAF 节流：逐 token 流式下每个 delta 都会触发 setMessages + ReactMarkdown 重解析，
  // 长文本会掉帧。把同一帧内多个 delta 合并成一次 setMessages（约 16ms 一次）。
  const rafRef = useRef<number | null>(null)

  /** 同步把 streamingRef 快照刷进 messages 状态（合并一帧内所有 delta 为一次渲染）。 */
  const flushStream = useCallback(() => {
    const streaming = streamingRef.current
    if (!streaming) return
    const snapshot = { ...streaming }
    setMessages((prev) => {
      const without = prev.filter((m) => m.id !== snapshot.id)
      return [...without, snapshot]
    })
  }, [])

  /** 调度一帧后的刷新，同帧多次调用只排一次 rAF。 */
  const scheduleFlush = useCallback(() => {
    if (rafRef.current != null) return
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null
      flushStream()
    })
  }, [flushStream])

  /** 取消挂起的刷新并清空 id（定稿/中断路径调用）。 */
  const cancelFlush = useCallback(() => {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
  }, [])

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

  // 挂载时拉取一次技能清单：skills_list 仅在后端连接时推送，sidepanel 可能晚开，
  // 需向 background 取缓存的副本（技能是静态的，无需轮询）。
  useEffect(() => {
    chrome.runtime.sendMessage({ type: 'get_skills' }, (res) => {
      if (!chrome.runtime.lastError && res) {
        setSkills((res.skills as SkillInfo[]) ?? [])
      }
    })
  }, [])

  // 监听 background 推送的消息
  useEffect(() => {
    const listener = (message: BackgroundMessage) => {
      if (message.type === 'stream') {
        const content = message.content ?? ''

        if (content === '[DONE]') {
          // 定稿前先取消挂起的 rAF 并同步落盘残余 delta，避免最后一帧丢失
          cancelFlush()
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
          cancelFlush()
          setMessages((prev) => [
            ...prev,
            { id: uid(), role: 'system', content: 'Agent 正在工作中，请等待...', timestamp: Date.now() },
          ])
          return
        }

        // 流式追加：先标记流式态（思考指示器/遮罩即时响应），再累积文本，rAF 节流刷新 UI
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
        // 首段 delta 立即刷新（建气泡），后续合并到下一帧，降低 ReactMarkdown 重解析频率
        if (streaming.content === content) {
          flushStream()
        } else {
          scheduleFlush()
        }
      }

      if (message.type === 'error') {
        cancelFlush()
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

      if (message.type === 'skills_list') {
        setSkills(message.skills ?? [])
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
    return () => {
      cancelFlush()
      chrome.runtime.onMessage.removeListener(listener)
    }
  }, [cancelFlush])

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
    cancelFlush()
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
  }, [cancelFlush])

const clearMessages = useCallback(() => {
    cancelFlush()
    // 通知后端开新会话（重置上下文）；停旧任务的职责由后端 new_session 分支承担
    chrome.runtime.sendMessage({ type: 'new_session' })
    setMessages([])
    streamingRef.current = null
    setIsStreaming(false)
    setError(null)
    setActivityStatus('idle')
  }, [cancelFlush])

  return { status, sendTask, messages, isStreaming, stopStream, error, clearMessages, activityStatus, skills }
}
