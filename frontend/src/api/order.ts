import { http, toPaged } from './http'

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
  /** 商品卖完下架后自动发布一件同样的新商品（网页版只能发 1 件库存时用） */
  auto_relist: boolean
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
  http.get<Order[]>('/orders', { params }).then(toPaged)
export const getOrder = (id: number) =>
  http.get<{ order: Order; deliveries: DeliveryRecord[] }>(`/orders/${id}`).then((r) => r.data)
export const syncOrders = (accountId: number) =>
  http.post<Record<string, number>>(`/orders/sync/${accountId}`, null, { timeout: 120_000 }).then((r) => r.data)
export const deliverOrder = (id: number) =>
  http
    .post<{ ok: boolean; status: string; error: string | null; code: 'no_binding' | null; item_id: string | null }>(
      `/orders/${id}/deliver`,
      null,
      { timeout: 120_000 },
    )
    .then((r) => r.data)
export const closeHold = (id: number) => http.post<{ status: string }>(`/orders/${id}/close-hold`).then((r) => r.data)
export const resolveManualOrder = (id: number, action: 'delivered' | 'closed' = 'delivered') =>
  http.post<{ status: string }>(`/orders/${id}/resolve-manual`, null, { params: { action } }).then((r) => r.data)

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

// ---------------------------------------------------------------- 买家分析（该不该卖给他）
export interface BuyerChatSignal {
  key: string
  label: string
  count: number
  evidence: string[]
  advice: string
}

export interface BuyerAnalysis {
  buyer_id: string
  nick: string
  avatar: string
  profile_error: string
  buyer_credit: string
  seller_credit: string
  item_cnt: number | null
  rate_cnt: number | null
  as_buyer: number
  as_buyer_positive: number
  as_buyer_negative: number
  negative_hits: [string, number][]
  positive_hits: [string, number][]
  negative_reviews: { content: string; rate: number | null; created_at: string; hits: string[] }[]
  chat_signals: BuyerChatSignal[]
  bargain_rounds: number
  history: {
    orders: number
    completed: number
    refunded: number
    closed: number
    total_amount: number
    blacklisted: boolean
    blacklist_reason: string
  }
  score: number
  level: string
  verdict: 'sell' | 'caution' | 'decline'
  highlights: string[]
  risks: string[]
  precautions: string[]
  analyzed_at: string
}

export interface BuyerInsight {
  verdict: 'sell' | 'caution' | 'decline'
  summary: string
  chat_assessment: string
  risk_points: string[]
  precautions: string[]
  suggested_reply: string
}

export interface BuyerRiskTarget {
  conv_id?: number
  order_pk?: number
  refresh?: boolean
}

export const buyerRiskAnalysis = (body: BuyerRiskTarget) =>
  http.post<BuyerAnalysis>('/buyer-risk/analysis', body, { timeout: 120_000 }).then((r) => r.data)
export const buyerRiskInsight = (body: BuyerRiskTarget) =>
  http
    .post<{ analysis: BuyerAnalysis; ai: BuyerInsight }>('/buyer-risk/insight', body, { timeout: 180_000 })
    .then((r) => r.data)
