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
  scheduled_at: string | null
}

export interface DraftOut extends DraftIn {
  id: number
  status: 'draft' | 'scheduled' | 'publishing' | 'published' | 'failed' | string
  item_id: string | null
  error: string | null
  created_at: string
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
export const uploadUrl = (imageId: string) => `/api/v1/goods/uploads/${imageId}`
export const aiCopy = (image_ids: string[], hint: string) =>
  http.post<CopyOut>('/goods/ai-copy', { image_ids, hint }, { timeout: 180_000 }).then((r) => r.data)

export const listDrafts = () => http.get<DraftOut[]>('/goods/drafts').then((r) => r.data)
export const createDraft = (body: DraftIn) => http.post<DraftOut>('/goods/drafts', body).then((r) => r.data)
export const updateDraft = (id: number, body: DraftIn) =>
  http.put<DraftOut>(`/goods/drafts/${id}`, body).then((r) => r.data)
export const deleteDraft = (id: number) => http.delete(`/goods/drafts/${id}`)
export const publishDraft = (id: number) =>
  http
    .post<{ item_id: string; published_at: string }>(`/goods/drafts/${id}/publish`, null, { timeout: 120_000 })
    .then((r) => r.data)
