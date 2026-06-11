import { ArrowLeft, Copy, Eye, EyeOff, Loader2 } from 'lucide-react'
import { useState } from 'react'
import type { AppConfig } from '@/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface ConfigPanelProps {
  config: AppConfig
  onSave: (config: AppConfig) => void
  onClose: () => void
}

export function ConfigPanel({ config, onSave, onClose }: ConfigPanelProps) {
  const [wsUrl, setWsUrl] = useState(config.wsUrl)
  const [model, setModel] = useState(config.model)
  const [token, setToken] = useState(config.token)
  const [showToken, setShowToken] = useState(false)
  const [saving, setSaving] = useState(false)
  const [copied, setCopied] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    onSave({ wsUrl, model, token })
    setSaving(false)
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(wsUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="flex flex-col h-full bg-background">
      <header className="flex items-center gap-2 border-b px-3 py-2">
        <Button variant="ghost" size="icon-sm" onClick={onClose} className="cursor-pointer" title="返回">
          <ArrowLeft className="size-3.5" />
        </Button>
        <span className="text-sm font-medium flex-1">设置</span>
      </header>

      <div className="flex flex-col gap-4 p-4">

      {/* WebSocket URL */}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="ws-url" className="text-xs text-muted-foreground">WebSocket URL</label>
        <div className="flex gap-2 items-center">
          <Input
            id="ws-url"
            placeholder="ws://localhost:8765"
            value={wsUrl}
            onChange={(e) => setWsUrl(e.target.value)}
            className="text-xs h-8"
          />
          <Button
            variant="outline"
            size="icon"
            className="h-8 w-8 shrink-0 cursor-pointer"
            onClick={handleCopy}
            title="复制"
          >
            {copied ? <span className="text-xs">✓</span> : <Copy className="size-3" />}
          </Button>
        </div>
      </div>

      {/* 模型 */}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="model" className="text-xs text-muted-foreground">模型</label>
        <select
          id="model"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className="h-8 text-xs rounded-md border border-input bg-background px-2 cursor-pointer"
        >
          <option value="default">默认模型</option>
          <option value="gpt-4o">GPT-4o</option>
          <option value="claude-sonnet">Claude Sonnet</option>
          <option value="claude-opus">Claude Opus</option>
        </select>
      </div>

      {/* 认证令牌 */}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="token" className="text-xs text-muted-foreground">认证令牌</label>
        <div className="flex gap-2 items-center">
          <Input
            id="token"
            type={showToken ? 'text' : 'password'}
            placeholder="输入认证令牌..."
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className="text-xs h-8"
          />
          <Button
            variant="outline"
            size="icon"
            className="h-8 w-8 shrink-0 cursor-pointer"
            onClick={() => setShowToken(!showToken)}
            title="显示/隐藏"
          >
            {showToken ? <EyeOff className="size-3" /> : <Eye className="size-3" />}
          </Button>
        </div>
      </div>

      {/* 操作按钮 */}
      <div className="flex gap-2 mt-2">
        <Button onClick={handleSave} disabled={saving} className="flex-1 h-8 text-xs cursor-pointer">
          {saving ? <Loader2 className="size-3 animate-spin" /> : '保存'}
        </Button>
      </div>
      </div>
    </div>
  )
}
