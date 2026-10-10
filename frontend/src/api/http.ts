import axios, { AxiosError, type AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'
import { getItem, removeItem, TOKEN_KEY, USER_KEY } from '@/utils/storage'

export const API_BASE = '/api/v1'

export const http = axios.create({
  baseURL: API_BASE,
  timeout: 60_000,
})

http.interceptors.request.use((config) => {
  const token = getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

/** 从 FastAPI 错误响应中提取可读信息：{detail: string} 或 422 校验列表 */
export function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as { detail?: unknown } | undefined
    const detail = data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((d: { loc?: (string | number)[]; msg?: string }) => {
          const loc = (d.loc || []).filter((x) => x !== 'body').join('.')
          return loc ? `${loc}：${d.msg}` : d.msg
        })
        .join('；')
    }
    if (err.response) return `请求失败（HTTP ${err.response.status}）`
    if (err.code === 'ECONNABORTED') return '请求超时'
    return '网络错误，无法连接服务器'
  }
  if (err instanceof Error) return err.message
  return String(err)
}

/** 分页列表：items 为当前页，total 为总数（来自响应头 X-Total-Count） */
export interface Paged<T> {
  items: T[]
  total: number
}

/** 把列表响应转换为 {items, total}；后端未返回 X-Total-Count 时退化为当前页长度 */
export function toPaged<T>(resp: AxiosResponse<T[]>): Paged<T> {
  const raw = resp.headers['x-total-count']
  const total = raw === undefined || raw === null || raw === '' ? NaN : Number(raw)
  return { items: resp.data, total: Number.isFinite(total) ? total : resp.data.length }
}

let redirecting = false

http.interceptors.response.use(
  (resp) => resp,
  (err: AxiosError) => {
    const status = err.response?.status
    const url = err.config?.url || ''
    if (status === 401 && !url.includes('/auth/login')) {
      removeItem(TOKEN_KEY)
      removeItem(USER_KEY)
      if (!redirecting && !location.pathname.startsWith('/login')) {
        redirecting = true
        ElMessage.warning('登录已失效，请重新登录')
        const back = encodeURIComponent(location.pathname + location.search)
        location.href = `/login?redirect=${back}`
      }
    } else if (status !== 428 && !(err.config as { silent?: boolean } | undefined)?.silent) {
      // 428 = 闲鱼要求先完成身份认证，由页面弹出认证二维码，不弹通用错误
      ElMessage.error(errorMessage(err))
    }
    return Promise.reject(err)
  },
)

declare module 'axios' {
  interface AxiosRequestConfig {
    /** 为 true 时不自动弹出错误提示 */
    silent?: boolean
  }
}

/** 带鉴权头下载文件（blob） */
export async function downloadBlob(url: string, filename: string, params?: Record<string, unknown>) {
  const resp = await http.get(url, { params, responseType: 'blob' })
  const href = URL.createObjectURL(resp.data as Blob)
  const a = document.createElement('a')
  a.href = href
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(href), 1000)
}
