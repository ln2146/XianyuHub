import { http } from './http'

export type OrderState =
  | 'pending_pay'
  | 'paid'
  | 'risk_hold'
  | 'delivering'
  | 'delivered'
  | 'deliver_failed'
  | 'manual'
  | 'completed'
  | 'refunding'
  | 'refunded'
  | 'closed'

export interface Order {
  id: number
  account_id: number
  order_id: string
  item_id: string | null
  item_title: string
  buyer_id: string | null
  buyer_nick: string
  amount: number | null
  quantity: number
  spec_name: string
  spec_value: string
  status: OrderState | string
  remote_status: string
  is_bargain: boolean
  paid_at: string | null
  delivered_at: string | null
  fail_reason: string | null
  retry_count: number
  created_at: string
}

export interface DeliveryRecord {
  id: number
  mode: string
  preview: string
  message_sent: boolean
  consigned: boolean
  success: boolean
  error: string | null
  created_at: string
}

export type PoolKind = 'text' | 'pool' | 'api'

export interface PoolIn {
  name: string
  kind: PoolKind
  text: string | null
  api_config: Record<string, unknown>
  low_stock_threshold: number
  enabled: boolean
}

export interface PoolOut {
  id: number
  name: string
  kind: PoolKind
  text_preview: string | null
  api_config: Record<string, unknown>
  low_stock_threshold: number
  enabled: boolean
  stock: { available: number; locked: number; used: number; [k: string]: number }
}

export interface CardItem {
  id: number
  masked: string
  status: 'available' | 'locked' | 'used' | string
  order_pk: number | null
  used_at: string | null
}

export interface BindingIn {
  pool_id: number
  account_id: number | null
  item_id: string
  spec_value: string | null
  template: string
  delay_seconds: number
  max_per_buyer: number
}

export interface BindingOut extends BindingIn {
  id: number
}

export interface BlacklistEntry {
  id: number
  buyer_id: string
  reason: string
  created_at: string
}

export const listOrders = (params: { account_id?: number; status?: string; q?: string; limit?: number; offset?: number }) =>
  http.get<Order[]>('/orders', { params }).then((r) => r.data)
export const getOrder = (id: number) =>
  http.get<{ order: Order; deliveries: DeliveryRecord[] }>(`/orders/${id}`).then((r) => r.data)
export const syncOrders = (accountId: number) =>
  http.post<Record<string, number>>(`/orders/sync/${accountId}`, null, { timeout: 120_000 }).then((r) => r.data)
export const deliverOrder = (id: number) =>
  http
    .post<{ ok: boolean; status: string; error: string | null }>(`/orders/${id}/deliver`, null, { timeout: 120_000 })
    .then((r) => r.data)
export const closeHold = (id: number) => http.post<{ status: string }>(`/orders/${id}/close-hold`).then((r) => r.data)

export const listPools = () => http.get<PoolOut[]>('/cards/pools').then((r) => r.data)
export const createPool = (body: PoolIn) => http.post<PoolOut>('/cards/pools', body).then((r) => r.data)
export const updatePool = (id: number, body: PoolIn) => http.put<PoolOut>(`/cards/pools/${id}`, body).then((r) => r.data)
export const deletePool = (id: number) => http.delete(`/cards/pools/${id}`)
export const importCards = (id: number, lines: string) =>
  http.post<{ added: number; duplicated: number }>(`/cards/pools/${id}/items`, { lines }).then((r) => r.data)
export const listCards = (id: number, status?: string) =>
  http.get<CardItem[]>(`/cards/pools/${id}/items`, { params: { status: status || undefined } }).then((r) => r.data)
export const deleteCard = (cardId: number) => http.delete(`/cards/items/${cardId}`)

export const listBindings = () => http.get<BindingOut[]>('/cards/bindings').then((r) => r.data)
export const createBinding = (body: BindingIn) => http.post<BindingOut>('/cards/bindings', body).then((r) => r.data)
export const updateBinding = (id: number, body: BindingIn) =>
  http.put<BindingOut>(`/cards/bindings/${id}`, body).then((r) => r.data)
export const deleteBinding = (id: number) => http.delete(`/cards/bindings/${id}`)

export const listBlacklist = () => http.get<BlacklistEntry[]>('/orders-blacklist').then((r) => r.data)
export const addBlacklist = (buyer_id: string, reason: string) =>
  http.post<{ buyer_id: string }>('/orders-blacklist', { buyer_id, reason }).then((r) => r.data)
export const removeBlacklist = (id: number) => http.delete(`/orders-blacklist/${id}`)
