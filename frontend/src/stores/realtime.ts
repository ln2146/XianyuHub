import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getItem, TOKEN_KEY } from '@/utils/storage'

export interface RealtimeEvent {
  event: 'message' | 'suggestion' | string
  data: Record<string, unknown> & { conversation_id?: number; account_id?: number; id?: number; text?: string }
}

type Listener = (ev: RealtimeEvent) => void

/** WebSocket 实时推送：自动重连（指数退避）+ 心跳 */
export const useRealtimeStore = defineStore('realtime', () => {
  const connected = ref(false)
  const listeners = new Set<Listener>()
  let ws: WebSocket | null = null
  let retry = 0
  let reconnectTimer: number | undefined
  let heartbeat: number | undefined
  let stopped = true

  function connect() {
    stopped = false
    const token = getItem(TOKEN_KEY)
    if (!token || ws) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const sock = new WebSocket(`${proto}://${location.host}/api/v1/ws?token=${encodeURIComponent(token)}`)
    ws = sock
    sock.onopen = () => {
      connected.value = true
      retry = 0
      heartbeat = window.setInterval(() => {
        if (sock.readyState === WebSocket.OPEN) sock.send('ping')
      }, 25_000)
    }
    sock.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data as string) as RealtimeEvent
        listeners.forEach((fn) => fn(ev))
      } catch {
        /* 忽略非 JSON 消息 */
      }
    }
    sock.onclose = (e) => {
      connected.value = false
      window.clearInterval(heartbeat)
      ws = null
      // 4401 = token 无效，不再重连
      if (stopped || e.code === 4401) return
      const delay = Math.min(30_000, 1000 * 2 ** retry) + Math.random() * 500
      retry += 1
      reconnectTimer = window.setTimeout(connect, delay)
    }
    sock.onerror = () => sock.close()
  }

  function disconnect() {
    stopped = true
    window.clearTimeout(reconnectTimer)
    window.clearInterval(heartbeat)
    ws?.close()
    ws = null
    connected.value = false
  }

  function subscribe(fn: Listener): () => void {
    listeners.add(fn)
    return () => listeners.delete(fn)
  }

  return { connected, connect, disconnect, subscribe }
})
