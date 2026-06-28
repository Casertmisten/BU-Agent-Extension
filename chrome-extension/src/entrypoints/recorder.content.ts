/** 录制 content script：动态注入，监听 background 的 start/stop 指令。
 *  与现有静态注册的 content.js 职责正交（那个执行 Agent 指令，这个录制用户操作）。 */

import { startRecording, type RecorderHandle } from '@/capture/recorder'
import type { CapturedEvent } from '@/capture/types'

export default defineContentScript({
  matches: ['<all_urls>'],
  // 不在 manifest 静态注册——由 background 用 chrome.scripting.executeScript 动态注入
  runAt: 'document_idle',
  async main() {
    let handle: RecorderHandle | null = null

    chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (message.type === 'record_start_content') {
        if (handle) {
          sendResponse({ started: false, reason: 'already_recording' })
          return false
        }
        handle = startRecording({
          traceId: message.trace_id,
          tabId: message.tab_id,
          sendEvent: (event: CapturedEvent) => {
            chrome.runtime.sendMessage({ type: 'record_event_content', event }).catch(() => {})
          },
        })
        sendResponse({ started: true })
        return false
      }

      if (message.type === 'record_stop_content') {
        if (handle) {
          handle.stop()
          handle = null
        }
        sendResponse({ stopped: true })
        return false
      }

      return false
    })
  },
})
