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

interface ValidationItem {
  loc?: (string | number)[]
  msg?: string
  type?: string
  ctx?: Record<string, unknown>
}

const FIELD_NAMES: Record<string, string> = {
  title: '标题',
  desc: '描述',
  price: '售价',
  orig_price: '原价',
  floor_price: '底价',
  quantity: '数量',
  image_ids: '图片',
  account_id: '账号',
  name: '名称',
  keyword: '关键词',
  keywords: '关键词',
  reply: '回复内容',
  cron: '定时规则',
  target_price: '目标价',
  drop_percent: '降幅',
  interval_minutes: '检查频率',
  template: '发货模板',
  cookies: 'Cookie',
  description: '需求描述',
  item: '商品链接',
}

function validationText(d: ValidationItem): string {
  const key = (d.loc || []).filter((x) => x !== 'body' && x !== 'query' && typeof x === 'string').pop() as
    | string
    | undefined
  const field = key ? FIELD_NAMES[key] || key : undefined
  const ctx = d.ctx || {}
  const why: Record<string, string> = {
    missing: '不能为空',
    string_too_short: '内容太短',
    string_too_long: '内容太长',
    greater_than: `需要大于 ${ctx.gt}`,
    greater_than_equal: `不能小于 ${ctx.ge}`,
    less_than: `需要小于 ${ctx.lt}`,
    less_than_equal: `不能大于 ${ctx.le}`,
    int_parsing: '需要填写整数',
    float_parsing: '需要填写数字',
    bool_parsing: '取值不正确',
    literal_error: '取值不在可选范围内',
    enum: '取值不在可选范围内',
    string_pattern_mismatch: '格式不正确',
    too_short: '至少需要填写一项',
    too_long: '填写的项太多',
  }
  // 我们自己写的校验（ValueError）本来就是中文说明：去掉「Value error, 」前缀直接显示
  const text = d.type === 'value_error' ? (d.msg || '').replace(/^Value error,\s*/, '') : why[d.type || ''] || '填写不正确'
  return field && d.type !== 'value_error' ? `「${field}」${text}` : text
}

/** 从 FastAPI 错误响应中提取可读信息：{detail: string} 或 422 校验列表 */
export function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as { detail?: unknown } | undefined
    const detail = data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      // 422 参数校验：不把 Pydantic 的英文原文直接给用户
      return detail.map(validationText).join('；')
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
