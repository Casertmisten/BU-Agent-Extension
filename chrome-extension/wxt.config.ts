import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'wxt'

export default defineConfig({
  srcDir: 'src',
  modules: ['@wxt-dev/module-react'],
  webExt: {
    chromiumArgs: ['--hide-crash-restore-bubble'],
  },
  vite: () => ({
    plugins: [tailwindcss()],
    define: {
      __VERSION__: JSON.stringify('0.2.0'),
    },
  }),
  manifest: {
    name: 'Browser Use Agent',
    description: '基于 SidePanel 的 AI 浏览器自动化',
    permissions: ['sidePanel', 'scripting', 'tabs', 'debugger', 'alarms', 'activeTab', 'storage'],
    host_permissions: ['<all_urls>'],
    action: {
      default_title: 'Browser Use Agent',
    },
    side_panel: {
      default_path: 'sidepanel/index.html',
    },
  },
})
