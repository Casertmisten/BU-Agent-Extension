/** 录制状态管理 hook：与 background 通信，监听 record_* 消息。 */

import { useEffect, useState, useCallback } from 'react'
import type {
  RecorderStatus,
  DistillStage,
  RecordStartedMsg,
  RecordDistillProgressMsg,
  RecordDoneMsg,
  RecordErrorMsg,
} from '@/types'

export interface RecorderState {
  status: RecorderStatus
  traceId: string | null
  startedAt: number | null
  eventCount: number
  distillStage: DistillStage | null
  distillMessage: string | null
  lastSkill: { name: string; path: string } | null
  error: string | null
}

const INITIAL: RecorderState = {
  status: 'idle',
  traceId: null,
  startedAt: null,
  eventCount: 0,
  distillStage: null,
  distillMessage: null,
  lastSkill: null,
  error: null,
}

export function useRecorder() {
  const [state, setState] = useState<RecorderState>(INITIAL)

  // 监听 background 转发的 record_* 消息
  useEffect(() => {
    const listener = (msg: Record<string, unknown>) => {
      const type = msg.type as string
      if (!type.startsWith('record_')) return

      if (type === 'record_started') {
        const m = msg as unknown as RecordStartedMsg
        setState({
          ...INITIAL,
          status: 'recording',
          traceId: m.trace_id,
          startedAt: Date.now(),
        })
      } else if (type === 'record_progress') {
        setState((s) => ({ ...s, eventCount: (msg.received_events as number) ?? s.eventCount }))
      } else if (type === 'record_distilling') {
        setState((s) => ({ ...s, status: 'distilling', distillStage: null, distillMessage: null }))
      } else if (type === 'record_distill_progress') {
        const m = msg as unknown as RecordDistillProgressMsg
        setState((s) => ({ ...s, distillStage: m.stage, distillMessage: m.message }))
      } else if (type === 'record_done') {
        const m = msg as unknown as RecordDoneMsg
        setState({
          ...INITIAL,
          status: 'done',
          lastSkill: { name: m.skill_name, path: m.skill_path },
        })
        // 3 秒后恢复 idle
        setTimeout(() => setState((s) => ({ ...s, status: 'idle' })), 3000)
      } else if (type === 'record_error') {
        const m = msg as unknown as RecordErrorMsg
        setState({
          ...INITIAL,
          status: 'idle',
          error: m.message,
          traceId: m.trace_id,
        })
      }
    }
    chrome.runtime.onMessage.addListener(listener)
    return () => chrome.runtime.onMessage.removeListener(listener)
  }, [])

  const start = useCallback(async (label: string) => {
    chrome.runtime.sendMessage({ type: 'record_start', label })
  }, [])

  const stop = useCallback(async (label?: string) => {
    chrome.runtime.sendMessage({ type: 'record_stop', label })
  }, [])

  const redistill = useCallback(async (traceId: string) => {
    chrome.runtime.sendMessage({ type: 'record_redistill', trace_id: traceId })
    setState((s) => ({ ...s, status: 'distilling', error: null }))
  }, [])

  const dismissError = useCallback(() => {
    setState((s) => ({ ...s, error: null }))
  }, [])

  return { state, start, stop, redistill, dismissError }
}
