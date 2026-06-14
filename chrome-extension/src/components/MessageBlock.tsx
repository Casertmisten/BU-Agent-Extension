import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Fragment } from 'react'
import type { Message } from '@/types'
import { ToolStepsPanel, ThinkingIndicator } from '@/components/EventCards'

/**
 * 单条消息渲染块 —— 聊天视图与历史详情视图共用。
 * - user：右对齐绿色气泡
 * - system：居中提示文字
 * - agent：工具步骤折叠面板 + Markdown 内容气泡
 */
export function MessageBlock({ message, activityStatus }: { message: Message; activityStatus?: string }) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end shrink-0">
        <div className="max-w-[85%] rounded-xl rounded-br-sm bg-gradient-to-br from-emerald-500 to-emerald-600 text-white px-3 py-2 text-xs whitespace-pre-wrap shadow-sm">
          {message.content}
        </div>
      </div>
    )
  }

  if (message.role === 'system') {
    return (
      <div className="text-center text-[11px] text-muted-foreground py-1 shrink-0">{message.content}</div>
    )
  }

  // Agent 消息：清理内容
  const displayContent = message.content
    .replace(/\r\n/g, '\n')
    .replace(/\n{2,}/g, '\n')
    .replace(/^\n+/, '')
    .trimEnd()

  const tokenUsage = message.events?.find(e => e.type === 'token_usage')?.data
  const visibleEvents = message.events?.filter(
    e => e.type !== 'activity_status' && e.type !== 'token_usage'
  ) || []
  const hasVisibleEvents = visibleEvents.length > 0
  // 历史会话永远视为已完成，不进入流式分支
  const isStreamingMsg = activityStatus != null && message.status === 'streaming'

  return (
    <Fragment>
      {/* 思考指示器 - 流式消息且无工具步骤时显示 */}
      {isStreamingMsg && !hasVisibleEvents && (
        <ThinkingIndicator />
      )}
      {/* 工具步骤折叠面板 */}
      {hasVisibleEvents && (
        <ToolStepsPanel events={message.events!} isStreaming={isStreamingMsg} />
      )}
      {/* Agent 内容气泡 */}
      {displayContent && (
        <div className="flex justify-start shrink-0">
          <div className="max-w-[85%] rounded-xl rounded-bl-sm border bg-card px-3 py-2 text-xs prose prose-xs prose-sm:max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-pre:my-1 prose-headings:my-1 shadow-sm">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayContent}</ReactMarkdown>
          </div>
        </div>
      )}
      {/* Token 消耗胶囊：一轮对话总 token，弱化元信息 */}
      {tokenUsage && typeof tokenUsage.input === 'number'
        && typeof tokenUsage.output === 'number' && (
        <div className="flex justify-start shrink-0">
          <span className="text-[10px] text-muted-foreground px-3 py-1">
            Token: 入 {tokenUsage.input.toLocaleString()} / 出 {tokenUsage.output.toLocaleString()}
          </span>
        </div>
      )}
    </Fragment>
  )
}
