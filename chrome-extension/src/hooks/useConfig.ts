import { useCallback, useEffect, useState } from 'react'
import type { AppConfig } from '@/types'

const STORAGE_KEY = 'bu-agent-config'

const DEFAULT_CONFIG: AppConfig = {
  wsUrl: 'ws://localhost:8765',
  model: 'default',
  token: '',
}

export function useConfig() {
  const [config, setConfig] = useState<AppConfig>(DEFAULT_CONFIG)
  const [loaded, setLoaded] = useState(false)

  // 加载配置
  useEffect(() => {
    chrome.storage.local.get(STORAGE_KEY, (result) => {
      if (result[STORAGE_KEY]) {
        setConfig({ ...DEFAULT_CONFIG, ...result[STORAGE_KEY] })
      }
      setLoaded(true)
    })
  }, [])

  const saveConfig = useCallback((newConfig: AppConfig) => {
    setConfig(newConfig)
    chrome.storage.local.set({ [STORAGE_KEY]: newConfig })
  }, [])

  const resetConfig = useCallback(() => {
    setConfig(DEFAULT_CONFIG)
    chrome.storage.local.remove(STORAGE_KEY)
  }, [])

  return { config, loaded, saveConfig, resetConfig }
}
