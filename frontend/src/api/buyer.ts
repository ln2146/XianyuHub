import { downloadBlob, http, toPaged } from './http'

export interface ItemRules {
  include_any: string[]
  include_all: string[]
  exclude: string[]
  min_price: number | null
  max_price: number | null
  areas: string[]
  max_age_hours: number | null
  min_seller_zhima: string | null
  min_seller_reg_days: number | null
  blacklist_sellers: string[]
}

export interface TaskIn {
  name: string
  keywords: string[]
  min_price: number | null
  max_price: number | null
  province: string | null
  city: string | null
  publish_days: number | null
  personal_only: boolean
  free_shipping: boolean
  sort: string
  max_pages: number
  rules: ItemRules
  criteria: string
  decision_mode: 'ai' | 'rule'
  analyze_images: boolean
  ai_prescreen: boolean
  fetch_seller_profile: boolean
  notify_conditional: boolean
  price_drop_percent: number
  account_id: number | null
  cron: string
  enabled: boolean
}

export interface TaskOut extends TaskIn {
  id: number
  last_run_at: string | null
  last_status: string | null
  last_error: string | null
  last_stats: Record<string, unknown>
  paused_reason: string | null
  running: boolean
  result_counts: Record<string, number>
}

/** /buyer/tasks/generate 返回的草稿（部分字段） */
export interface TaskDraft {
  name: string
  keywords: string[]
  min_price: number | null
  max_price: number | null
  province: string | null
  city: string | null
  publish_days: number | null
  personal_only: boolean
  rules: { include_all: string[]; exclude: string[] }
  criteria: string
}

export type UserMark = 'none' | 'favorite' | 'ignored' | 'bought' | 'seen'

export interface ResultItem {
  title: string
  price: number | null
  orig_price: number | null
  area: string
  image_url: string
  link: string
  want_cnt: number | null
  browse_cnt: number | null
  seller_nick: string
  seller_zhima: string
  publish_time: string | null
  tags: string[]
}

export interface ResultOut {
  id: number
  task_id: number
  item_id: string
  stage: string
  verdict: 'recommend' | 'conditional' | 'reject' | null
  confidence: number | null
  reason: string
  filter_reasons: string[]
  risk_tags: string[]
  need_confirm: string[]
  questions: string[]
  seller_type: string | null
  deal_score: number | null
  deal_label: string
  mark: UserMark
  created_at: string
  item: ResultItem
}

export interface ResultQuery {
  task_id?: number
  verdict?: string
  mark?: string
  q?: string
  sort?: 'newest' | 'price_asc' | 'deal'
  limit?: number
  offset?: number
}

export interface MarketStats {
  count: number
  min: number
  p25: number
  median: number
  p75: number
  max: number
  mean: number
}

export const emptyRules = (): ItemRules => ({
  include_any: [],
  include_all: [],
  exclude: [],
  min_price: null,
  max_price: null,
  areas: [],
  max_age_hours: null,
  min_seller_zhima: null,
  min_seller_reg_days: null,
  blacklist_sellers: [],
})

export const emptyTask = (): TaskIn => ({
  name: '',
  keywords: [],
  min_price: null,
  max_price: null,
  province: null,
  city: null,
  publish_days: null,
  personal_only: false,
  free_shipping: false,
  sort: 'newest',
  max_pages: 1,
  rules: emptyRules(),
  criteria: '',
  decision_mode: 'ai',
  analyze_images: true,
  ai_prescreen: true,
  fetch_seller_profile: false,
  notify_conditional: false,
  price_drop_percent: 5,
  account_id: null,
  cron: '*/30 8-23 * * *',
  enabled: true,
})

export const listTasks = () => http.get<TaskOut[]>('/buyer/tasks').then((r) => r.data)
export const createTask = (body: TaskIn) => http.post<TaskOut>('/buyer/tasks', body).then((r) => r.data)
export const updateTask = (id: number, body: TaskIn) =>
  http.put<TaskOut>(`/buyer/tasks/${id}`, body).then((r) => r.data)
export const deleteTask = (id: number) => http.delete(`/buyer/tasks/${id}`)
export const runTask = (id: number) => http.post<{ started: boolean }>(`/buyer/tasks/${id}/run`).then((r) => r.data)
export const generateTask = (description: string) =>
  http.post<TaskDraft>('/buyer/tasks/generate', { description }, { timeout: 120_000 }).then((r) => r.data)
export const taskMarket = (id: number) => http.get<MarketStats>(`/buyer/tasks/${id}/market`).then((r) => r.data)

export const listResults = (params: ResultQuery) =>
  http.get<ResultOut[]>('/buyer/results', { params }).then(toPaged)
export const markResult = (id: number, mark: UserMark) =>
  http.patch<{ mark: UserMark }>(`/buyer/results/${id}`, { mark }).then((r) => r.data)
export const exportResults = (task_id?: number) =>
  downloadBlob('/buyer/results/export.csv', `选品结果-${Date.now()}.csv`, task_id ? { task_id } : undefined)
export const priceHistory = (itemId: string) =>
  http.get<{ price: number; seen_at: string }[]>(`/buyer/items/${itemId}/prices`).then((r) => r.data)

export interface SearchItem {
  item_id: string
  title: string
  price: number | null
  price_text: string
  orig_price: number | null
  want_cnt: number | null
  browse_cnt: number | null
  area: string
  seller_nick: string
  seller_id: string | null
  image_url: string
  images: string[]
  publish_time: string | null
  link: string
  tags: string[]
  desc: string
}

export interface SearchPage {
  items: SearchItem[]
  page: number
  has_more: boolean
}

export interface LiveSearchQuery {
  keyword: string
  page?: number
  sort?: 'newest' | 'price_asc' | 'price_desc' | 'default'
  min_price?: number | null
  max_price?: number | null
  province?: string | null
  city?: string | null
  publish_days?: number | null
  personal_only?: boolean
  free_shipping?: boolean
  account_id?: number | null
}

export interface SellerInfo {
  seller_id: string | null
  nick: string
  zhima_level: string
  reg_days: number | null
  sold_cnt: number | null
}

export interface ItemDetail {
  item: SearchItem
  seller: SellerInfo
  status: string
}

export const liveSearch = (params: LiveSearchQuery) =>
  http.get<SearchPage>('/buyer/search', { params }).then((r) => r.data)

export const getItemDetail = (itemId: string, account_id?: number | null) =>
  http
    .get<ItemDetail>(`/buyer/items/${itemId}/detail`, { params: account_id ? { account_id } : undefined })
    .then((r) => r.data)

