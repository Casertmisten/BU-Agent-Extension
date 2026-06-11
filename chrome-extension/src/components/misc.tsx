import { History, Settings } from 'lucide-react'
import { TypingAnimation } from '@/components/ui/typing-animation'
import { cn } from '@/lib/utils'

/** 状态圆点 */
export function StatusDot({ status }: { status: 'connected' | 'disconnected' | 'running' }) {
  const colorClass = {
    connected: 'bg-green-500',
    disconnected: 'bg-red-500',
    running: 'bg-blue-500 animate-pulse',
  }[status]

  const label = {
    connected: '就绪',
    disconnected: '未连接',
    running: '运行中',
  }[status]

  return (
    <div className="flex items-center gap-1.5 mr-2">
      <span className={cn('size-2 rounded-full', colorClass)} />
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  )
}

/** Logo 图标 */
export function Logo({ className }: { className?: string }) {
  return (
    <img src="/assets/logo.png" alt="Logo" className={cn('size-8 rounded-lg shadow-lg', className)} />
  )
}

/** 空状态：呼吸渐变 + 打字机欢迎语 */
export function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-6">
      <div className="relative select-none pointer-events-none">
        <div className="absolute inset-0 -m-6 rounded-full bg-[conic-gradient(from_180deg,oklch(0.55_0.2_280),oklch(0.5_0.15_230),oklch(0.6_0.18_310),oklch(0.55_0.2_280))] blur-2xl animate-[glow-a_5s_ease-in-out_infinite]" />
        <div className="absolute inset-0 -m-6 rounded-full bg-[conic-gradient(from_0deg,oklch(0.55_0.18_160),oklch(0.5_0.2_200),oklch(0.6_0.15_120),oklch(0.55_0.18_160))] blur-2xl animate-[glow-b_5s_ease-in-out_infinite]" />
        <Logo className="relative size-20 opacity-80" />
      </div>
      <div>
        <h2 className="text-base font-medium text-foreground mb-1">Page Agent Ext</h2>
        <TypingAnimation
          className="text-sm text-muted-foreground"
          words={[
            '输入任务以自动化此页面',
            '执行多步骤页面操作',
            'AI 驱动的浏览器自动化',
          ]}
          cursorStyle="underscore"
          loop
          startOnView={false}
          typeSpeed={20}
          deleteSpeed={10}
          pauseDelay={3000}
        />
      </div>
    </div>
  )
}

/** 顶部导航按钮 */
export function NavButtons({
  onHistory,
  onSettings,
}: {
  onHistory: () => void
  onSettings: () => void
}) {
  return (
    <div className="flex items-center gap-1">
      <button
        onClick={onHistory}
        className="size-7 flex items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors cursor-pointer"
        title="历史记录"
      >
        <History className="size-3.5" />
      </button>
      <button
        onClick={onSettings}
        className="size-7 flex items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors cursor-pointer"
        title="设置"
      >
        <Settings className="size-3.5" />
      </button>
    </div>
  )
}
