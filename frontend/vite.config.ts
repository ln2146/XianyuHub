import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

/** 从模块路径中取出（最内层 node_modules 下的）包名，兼容 pnpm 的 .pnpm 目录结构 */
function packageOf(id: string): string | null {
  const m = id.match(/.*[\\/]node_modules[\\/]((?:@[^\\/]+[\\/])?[^\\/]+)/)
  return m ? m[1]!.replace(/\\/g, '/') : null
}

// 开发代理目标：默认本机 8001 端口的后端；若有环境变量则优先使用 VITE_API_TARGET
const API_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:8001'

type PkgMatcher = (pkg: string) => boolean
const VUE_PKGS: PkgMatcher = (p) => ['vue', 'vue-router', 'pinia', 'vue-demi'].includes(p) || p.startsWith('@vue/')
// element-plus、图标及其运行时依赖
const ELEMENT_PKGS: PkgMatcher = (p) =>
  ['element-plus', 'async-validator', 'dayjs', 'memoize-one', 'normalize-wheel-es', '@ctrl/tinycolor', '@popperjs/core'].includes(p) ||
  /^(@element-plus|@floating-ui|@vueuse)\//.test(p) ||
  p.startsWith('lodash')
const ECHARTS_PKGS: PkgMatcher = (p) => p === 'echarts' || p === 'zrender' || p === 'tslib'

function isPkg(id: string, match: PkgMatcher): boolean {
  const pkg = packageOf(id)
  return !!pkg && match(pkg)
}

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      // WebSocket 实时推送（需放在 /api 之前，确保 ws 升级被代理）
      '/api/v1/ws': { target: API_TARGET, ws: true, changeOrigin: true },
      '/api': { target: API_TARGET, changeOrigin: true },
    },
  },
  build: {
    chunkSizeWarningLimit: 1000,
    // Vite 8 基于 Rolldown：rollupOptions.output.manualChunks 已废弃，且其单分组语义会把 vue 运行时
    // 连同依赖一起并入先命中的 element-plus 分组。改用 codeSplitting 分组 + 优先级，保证 vue 单独成块。
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: 'vendor-vue', test: (id: string) => isPkg(id, VUE_PKGS), priority: 30 },
            { name: 'vendor-element', test: (id: string) => isPkg(id, ELEMENT_PKGS), priority: 20 },
            { name: 'vendor-echarts', test: (id: string) => isPkg(id, ECHARTS_PKGS), priority: 10 },
          ],
        },
      },
    },
  },
})
