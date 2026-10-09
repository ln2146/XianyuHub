import { http } from './http'

export type AccountStatus = 'active' | 'need_login' | 'cooldown' | 'circuit_open' | 'disabled'

export interface AccountSettings {
  auto_reply: boolean
  keyword_reply: boolean
  ai_mode: 'off' | 'suggest' | 'auto'
  takeover_minutes: number
  reply_delay_min: number
  reply_delay_max: number
  merge_window_seconds: number
  work_hours: string | null
  default_reply: string | null
  auto_delivery: boolean
  delivery_mode: 'confirm_then_send' | 'send_then_confirm' | 'send_only'
  auto_rate: boolean
  rate_text: string
  auto_polish: boolean
}

export interface Account {
  id: number
  owner_id: number
  unb: string
  nickname: string
  remark: string
  avatar: string
  status: AccountStatus | string
  health_score: number
  strikes: number
  cooldown_until: string | null
  last_error: string | null
  punish_url: string | null
  has_proxy: boolean
  settings: AccountSettings
  last_probe_at: string | null
  created_at: string
}

export interface AccountUpdate {
  remark?: string
  /** 空字符串表示清除代理 */
  proxy?: string
  settings?: Partial<AccountSettings>
  enabled?: boolean
}

export interface RiskEvent {
  id: number
  state: string
  reason: string
  punish_url: string | null
  created_at: string
  resolved_at: string | null
}

export type QrStatus = 'NEW' | 'SCANED' | 'CONFIRMED' | 'EXPIRED' | 'CANCELED' | 'NEED_VERIFY' | 'SUCCESS' | 'ERROR'

export interface QrPoll {
  status: QrStatus
  account_id: number | null
  verify_url: string | null
  message: string | null
}

export const listAccounts = () => http.get<Account[]>('/accounts').then((r) => r.data)
export const getAccount = (id: number) => http.get<Account>(`/accounts/${id}`).then((r) => r.data)
export const importCookies = (body: { cookies: string; proxy?: string | null; verify?: boolean }) =>
  http.post<Account>('/accounts/import', body).then((r) => r.data)
export const qrStart = (proxy?: string | null) =>
  http.post<{ qr_id: string; qr_content: string }>('/accounts/qr', { proxy: proxy || null }).then((r) => r.data)
export const qrPoll = (qrId: string) =>
  http.get<QrPoll>(`/accounts/qr/${qrId}`, { silent: true }).then((r) => r.data)
export const updateAccount = (id: number, body: AccountUpdate) =>
  http.patch<Account>(`/accounts/${id}`, body).then((r) => r.data)
export const deleteAccount = (id: number) => http.delete(`/accounts/${id}`)
export const probeAccount = (id: number) =>
  http.post<{ ok: boolean; status: string }>(`/accounts/${id}/probe`).then((r) => r.data)
export const resolveRisk = (id: number) =>
  http.post<{ status: string }>(`/accounts/${id}/resolve`).then((r) => r.data)
export const listRiskEvents = (id: number) =>
  http.get<RiskEvent[]>(`/accounts/${id}/risk-events`).then((r) => r.data)
