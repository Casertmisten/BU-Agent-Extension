/** 录制编排：组合 action-recorder + mutation-summary-recorder。
 *  在 content script 中安装/卸载，捕获的事件经 sendEvent 回调发回 background。 */

import { installActionRecorder, type InstalledCapture } from './action-recorder';
import { installMutationSummaryRecorder } from './mutation-summary-recorder';
import type { CapturedEvent } from './types';

export type RecorderHandle = {
  stop: () => CapturedEvent[]  // 停止并返回 flush 出的剩余事件
}

export type RecorderOptions = {
  traceId: string
  tabId: number
  sendEvent: (event: CapturedEvent) => void
}

/** 安装录制器，返回 handle（stop 时卸载并 flush）。 */
export function startRecording(options: RecorderOptions): RecorderHandle {
  const { traceId, tabId, sendEvent } = options

  const actionCapture = installActionRecorder({
    traceId,
    tabId,
    sendEvent,
  })

  const mutationCapture = installMutationSummaryRecorder({
    traceId,
    tabId,
    sendEvent,
  })

  return {
    stop() {
      actionCapture.stop()
      // mutation-summary 的 stop() 内部会 flush 剩余事件（通过 sendEvent），
      // 但 sendEvent 是同步的，flush 的事件已发出；这里返回空数组保持接口一致
      mutationCapture.stop()
      return []
    },
  }
}
