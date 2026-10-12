// 与浏览器扩展「鱼塘管家 · 登录态助手」通信：扩展在本页注入 bridge.js，双方通过 window.postMessage 往来
import { getCookieSyncToken } from '@/api/account'

const PAGE = 'xh-page'
const HELPER = 'xh-helper'

export interface HelperLoginState {
  loggedIn: boolean
  nick: string
  unb: string
}

export interface HelperCookies extends HelperLoginState {
  cookies: { name: string; value: string; domain: string }[]
}

export class HelperError extends Error {}

/** 扩展已注入时返回它的版本号 */
export function helperVersion(): string | undefined {
  return document.documentElement.dataset.xhHelper
}

function call<T>(type: string, payload: Record<string, unknown> = {}, timeoutMs = 120_000): Promise<T> {
  return new Promise((resolve, reject) => {
    const id = Math.random().toString(36).slice(2)
    const timer = window.setTimeout(() => {
      window.removeEventListener('message', onMessage)
      reject(new HelperError('浏览器扩展没有响应，请刷新页面后重试'))
    }, timeoutMs)
    function onMessage(ev: MessageEvent) {
      const d = ev.data
      if (ev.source !== window || !d || d.source !== HELPER || d.id !== id) return
      window.clearTimeout(timer)
      window.removeEventListener('message', onMessage)
      if (d.error === 'denied') reject(new HelperError('你在弹出的确认框里拒绝了读取'))
      else if (d.error) reject(new HelperError(`浏览器扩展出错：${d.error}`))
      else resolve(d as T)
    }
    window.addEventListener('message', onMessage)
    window.postMessage({ ...payload, source: PAGE, type, id }, window.location.origin)
  })
}

/** 读取这个浏览器里的闲鱼登录态（每个管理台地址第一次读取时，扩展会弹框请你确认） */
export const getBrowserCookies = () => call<HelperCookies>('get-cookies')

/** 让扩展在账号掉线时用浏览器里的登录态自动恢复（token 为只能同步登录态的专用令牌） */
export const enableAutoRenew = (token: string) => call<{ ok: boolean }>('enable-sync', { token })

/** 申请专用令牌并交给扩展，开启自动续期 */
export async function turnOnAutoRenew(): Promise<void> {
  const { token } = await getCookieSyncToken()
  await enableAutoRenew(token)
}
