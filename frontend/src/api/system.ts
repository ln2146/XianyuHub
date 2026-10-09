import { http, toPaged } from './http'

export type Role = 'admin' | 'operator' | 'member'

export interface UserOut {
  id: number
  username: string
  role: Role
  is_active: boolean
  last_login_at: string | null
}

export interface TokenOut {
  access_token: string
  token_type: string
  user: UserOut
}

export interface UserCreate {
  username: string
  password: string
  role: Role
}

export interface UserUpdate {
  role?: Role
  is_active?: boolean
  password?: string
}

export interface AuditOut {
  id: number
  created_at: string
  user_id: number | null
  actor_type: string
  action: string
  account_id: number | null
  target_type: string | null
  target_id: string | null
  success: boolean
  detail: Record<string, unknown>
  error: string | null
}

export const login = (username: string, password: string) =>
  http.post<TokenOut>('/auth/login', { username, password }).then((r) => r.data)

export const me = () => http.get<UserOut>('/auth/me').then((r) => r.data)

export const changePassword = (old_password: string, new_password: string) =>
  http.post('/auth/password', { old_password, new_password })

export const listUsers = () => http.get<UserOut[]>('/users').then((r) => r.data)
export const createUser = (body: UserCreate) => http.post<UserOut>('/users', body).then((r) => r.data)
export const updateUser = (id: number, body: UserUpdate) =>
  http.patch<UserOut>(`/users/${id}`, body).then((r) => r.data)
/** 删除用户；名下仍有账号 / 任务 / 卡券时返回 409（silent，由调用方展示后端说明） */
export const deleteUser = (id: number) => http.delete(`/users/${id}`, { silent: true })

export const listAuditLogs = (params: { action?: string; account_id?: number; limit?: number; offset?: number }) =>
  http.get<AuditOut[]>('/audit-logs', { params }).then(toPaged)

export interface SelfCheckItem {
  name: string
  title: string
  ok: boolean
  skipped: boolean
  ms: number
  detail: string
  /** 字段 -> 覆盖率（0~1） */
  coverage: Record<string, number> | null
}

export interface SelfCheckResult {
  ok: boolean
  started_at: string
  checks: SelfCheckItem[]
}

export const runSelfCheck = (body: { keyword: string; account_id: number | null }) =>
  http.post<SelfCheckResult>('/system/selfcheck', body, { timeout: 120_000 }).then((r) => r.data)
