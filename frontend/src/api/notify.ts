import { http } from './http'

export interface NotifyMeta {
  /** 渠道类型 -> 必填配置项 */
  types: Record<string, string[]>
  events: string[]
}

export interface Channel {
  id: number
  name: string
  type: string
  config: Record<string, unknown>
  events: string[]
  enabled: boolean
  last_error: string | null
}

export interface ChannelIn {
  name: string
  type: string
  config: Record<string, unknown>
  events: string[]
  enabled: boolean
}

export const getNotifyMeta = () => http.get<NotifyMeta>('/notify/meta').then((r) => r.data)
export const listChannels = () => http.get<Channel[]>('/notify/channels').then((r) => r.data)
export const createChannel = (body: ChannelIn) => http.post<Channel>('/notify/channels', body).then((r) => r.data)
export const updateChannel = (id: number, body: Partial<Omit<ChannelIn, 'type'>>) =>
  http.patch<Channel>(`/notify/channels/${id}`, body).then((r) => r.data)
export const deleteChannel = (id: number) => http.delete(`/notify/channels/${id}`)
export const testChannel = (id: number) =>
  http.post<{ ok: boolean; error: string | null }>(`/notify/channels/${id}/test`).then((r) => r.data)
