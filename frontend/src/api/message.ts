import { http, toPaged } from './http'

export type MessageSource =
  | 'buyer'
  | 'seller_app'
  | 'web_manual'
  | 'auto_keyword'
  | 'auto_ai'
  | 'auto_default'
  | 'delivery'
  | 'system'

export interface Conversation {
  id: number
  account_id: number
  cid: string
  peer_id: string | null
  peer_name: string
  item_id: string | null
  last_message: string
  last_message_at: string | null
  unread: number
  takeover_until: string | null
  bargain_rounds: number
  in_takeover: boolean
}

export interface ChatMessage {
  id: number
  direction: 'in' | 'out' | string
  source: MessageSource | string
  text: string
  is_system: boolean
  notice: string | null
  created_at: string
}

export interface Suggestion {
  id: number
  text: string
  intent: string
  note: string
  created_at: string
}

export interface RuleIn {
  name: string
  account_id: number | null
  item_id: string | null
  keywords: string[]
  match: 'contains' | 'exact' | 'regex'
  reply: string
  priority: number
  reply_once: boolean
  enabled: boolean
}

export interface RuleOut extends RuleIn {
  id: number
  hits: number
}

/** 试运行返回的回复计划：{action, text, source, intent, note, ...} */
export interface ReplyPlan {
  action: 'send' | 'suggest' | 'handoff' | 'none' | string
  text?: string
  source?: string
  intent?: string
  note?: string
  [k: string]: unknown
}

export interface ImStatus {
  running: boolean
  accounts: Record<string, { connected: boolean; [k: string]: unknown }>
}

export const listConversations = (params: { account_id?: number; q?: string; limit?: number; offset?: number }) =>
  http.get<Conversation[]>('/messages/conversations', { params }).then(toPaged)
export const listMessages = (convId: number, before_id?: number) =>
  http
    .get<ChatMessage[]>(`/messages/conversations/${convId}/messages`, { params: { before_id } })
    .then((r) => r.data)
export const markRead = (convId: number) =>
  http.post(`/messages/conversations/${convId}/read`, null, { silent: true })
export const sendMessage = (convId: number, text: string) =>
  http.post<ChatMessage>(`/messages/conversations/${convId}/send`, { text }).then((r) => r.data)
export const setTakeover = (convId: number, minutes: number) =>
  http.post<Conversation>(`/messages/conversations/${convId}/takeover`, { minutes }).then((r) => r.data)
export const listSuggestions = (convId: number) =>
  http.get<Suggestion[]>(`/messages/conversations/${convId}/suggestions`).then((r) => r.data)
export const handleSuggestion = (id: number, action: 'send' | 'discard') =>
  http.post<{ status: string }>(`/messages/suggestions/${id}/${action}`).then((r) => r.data)
export const testReply = (conversation_id: number, text: string) =>
  http.post<ReplyPlan>('/messages/test-reply', { conversation_id, text }, { timeout: 120_000 }).then((r) => r.data)

export const listRules = () => http.get<RuleOut[]>('/messages/rules').then((r) => r.data)
export const createRule = (body: RuleIn) => http.post<RuleOut>('/messages/rules', body).then((r) => r.data)
export const updateRule = (id: number, body: RuleIn) =>
  http.put<RuleOut>(`/messages/rules/${id}`, body).then((r) => r.data)
export const deleteRule = (id: number) => http.delete(`/messages/rules/${id}`)
export const getImStatus = () => http.get<ImStatus>('/messages/im-status').then((r) => r.data)

/** 售后 / 纠纷举证材料（Markdown）：订单、发货记录与完整聊天记录 */
export const conversationEvidence = (id: number) =>
  http.get<{ markdown: string; filename: string }>(`/messages/conversations/${id}/evidence`).then((r) => r.data)
