import { http } from './http'
import type { MarketStats } from './buyer'

export interface MyItem {
  id: number
  account_id: number
  item_id: string
  title: string
  price: number | null
  image_url: string
  status: 'on_sale' | 'sold' | 'offline' | string
  desc: string
  floor_price: number | null
  max_rounds: number
  step_ratios: number[]
  gifts: string
  knowledge: string
  is_virtual: boolean
  synced_at: string | null
  last_polished_at: string | null
  want_cnt?: number | null
  browse_cnt?: number | null
  publish_time?: string | null
  /** 数据最近一次从商品详情补全的时间；为空表示还没补全 */
  stats_at?: string | null
}

export interface ItemUpdate {
  floor_price?: number | null
  max_rounds?: number
  step_ratios?: number[]
  gifts?: string
  knowledge?: string
  desc?: string
  is_virtual?: boolean
}

export interface PriceSuggestion {
  quick_sale: number
  market: number
  premium: number
  basis: MarketStats
}

export interface MarketView {
  keyword: string
  sample: number
  suggestion: PriceSuggestion | null
  cheaper_competitors: { title: string; price: number | null; link: string; area: string }[]
}

export type ShippingMode = 'free' | 'by_distance' | 'fixed' | 'no_shipping'

/** 宝贝所在地（字段名与闲鱼一致，坐标为 GCJ-02） */
export interface ItemLocation {
  prov: string
  city: string
  area: string
  divisionId: number
  poiId: string
  poi: string
  address: string
  longitude: number
  latitude: number
}

export interface LocationOptions {
  /** 上次发布用的所在地 */
  saved: ItemLocation | null
  /** 账号在闲鱼 App 里的常用地址 */
  common: ItemLocation[]
  /** 坐标附近的地点 */
  nearby: ItemLocation[]
}

export interface PublishMeta {
  /** 能否设多库存（闲鱼只对部分卖家开放；不支持时卖出一件后自动下架） */
  support_inventory: boolean
  /** 账号当前被限制发布 */
  limited: boolean
  limit_title: string
  limit_content: string
}

export const getPublishMeta = (account_id: number) =>
  http.get<PublishMeta>('/goods/publish-meta', { params: { account_id }, silent: true }).then((r) => r.data)

export const getLocations = (account_id: number, coords?: { longitude: number; latitude: number }) =>
  http.get<LocationOptions>('/goods/locations', { params: { account_id, ...coords } }).then((r) => r.data)

export interface DraftIn {
  account_id: number
  title: string
  desc: string
  image_ids: string[]
  price: number
  orig_price: number | null
  quantity: number
  shipping: ShippingMode
  post_fee: number
  self_pickup: boolean
  floor_price: number | null
  knowledge: string
  is_virtual: boolean
  /** 为空时沿用账号上次使用的所在地 */
  location: ItemLocation | null
  scheduled_at: string | null
}

export interface DraftOut extends DraftIn {
  id: number
  status: 'draft' | 'scheduled' | 'publishing' | 'published' | 'failed' | string
  item_id: string | null
  error: string | null
  created_at: string
  /** AI 生成草稿时的附加信息；手动创建的草稿为 null */
  ai_meta: AiMeta | null
}

export type PriceStrategy = 'quick' | 'market' | 'premium'

export interface AiMeta {
  generated_at: string
  model: string
  strategy: PriceStrategy
  hint?: string
  titles: string[]
  brand_model: string
  condition: string
  category_hint: string
  highlights: string[]
  flaws: string[]
  accessories: string[]
  shipping_reason: string
  price_source: string
  price_guess: number | null
  search_keyword: string
  market: MarketView | null
  /** 需要卖家确认的信息 */
  uncertain: string[]
  /** 系统提醒（估价、已删除的违规表述等） */
  warnings: string[]
  removed: string[]
  cover_changed: boolean
}

export interface AiDraftIn {
  account_id: number
  image_ids: string[]
  hint: string
  strategy: PriceStrategy
  draft_id?: number | null
}

export interface CopyOut {
  titles: string[]
  desc: string
  search_keyword: string
  condition: string
  highlights: string[]
  market: MarketView | null
}

export const syncItems = (accountId: number) =>
  http.post<Record<string, number>>(`/goods/accounts/${accountId}/sync`, null, { timeout: 120_000 }).then((r) => r.data)
export const listItems = (params: { account_id?: number; status?: string; q?: string }) =>
  http.get<MyItem[]>('/goods/items', { params }).then((r) => r.data)
export const updateItem = (id: number, body: ItemUpdate) =>
  http.patch<MyItem>(`/goods/items/${id}`, body).then((r) => r.data)
export const polishItem = (id: number) => http.post<{ ok: boolean }>(`/goods/items/${id}/polish`).then((r) => r.data)
export const offlineItem = (id: number) => http.post<{ ok: boolean }>(`/goods/items/${id}/offline`).then((r) => r.data)
export const getMarket = (keyword: string, my_price?: number | null) =>
  http
    .get<MarketView>('/goods/market', { params: { keyword, my_price: my_price ?? undefined }, timeout: 90_000 })
    .then((r) => r.data)

export const uploadImage = (file: File) => {
  const fd = new FormData()
  fd.append('file', file)
  return http.post<{ id: string; url: string }>('/goods/uploads', fd).then((r) => r.data)
}
export const importImageUrl = (url: string) =>
  http.post<{ id: string; url: string }>('/goods/import-image-url', { url }).then((r) => r.data)
export const uploadUrl = (imageId: string) => `/api/v1/goods/uploads/${imageId}`
export const aiCopy = (image_ids: string[], hint: string) =>
  http.post<CopyOut>('/goods/ai-copy', { image_ids, hint }, { timeout: 180_000 }).then((r) => r.data)

export const listDrafts = () => http.get<DraftOut[]>('/goods/drafts').then((r) => r.data)
/** AI 根据图片生成整份草稿（耗时较长，通常 30~90 秒） */
export const aiDraft = (body: AiDraftIn) =>
  http.post<DraftOut>('/goods/ai-draft', body, { timeout: 300_000 }).then((r) => r.data)
export const createDraft = (body: DraftIn) => http.post<DraftOut>('/goods/drafts', body).then((r) => r.data)
export const updateDraft = (id: number, body: DraftIn) =>
  http.put<DraftOut>(`/goods/drafts/${id}`, body).then((r) => r.data)
export const deleteDraft = (id: number) => http.delete(`/goods/drafts/${id}`)
export const publishDraft = (id: number) =>
  http
    .post<{ item_id: string; published_at: string }>(`/goods/drafts/${id}/publish`, null, { timeout: 120_000 })
    .then((r) => r.data)
