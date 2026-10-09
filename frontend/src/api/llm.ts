import { http } from './http'

export type LlmKind = 'anthropic' | 'openai_compatible'

export interface LlmPreset {
  id: string
  name: string
  kind: LlmKind
  base_url: string
  models: { vision: string; chat: string; fast: string }
  note: string
}

export interface LlmMeta {
  kinds: LlmKind[]
  presets: LlmPreset[]
}

export interface LlmProvider {
  id: number
  name: string
  kind: LlmKind
  base_url: string
  api_key_masked: string
  has_api_key: boolean
  model_vision: string
  model_chat: string
  model_fast: string
  timeout_seconds: number
  anthropic_fallbacks: boolean
  daily_token_budget: number | null
  enabled: boolean
  is_active: boolean
  last_test_at: string | null
  last_test_ok: boolean | null
  last_error: string | null
}

export interface LlmProviderIn {
  name: string
  kind: LlmKind
  base_url: string
  api_key: string
  model_vision: string
  model_chat: string
  model_fast: string
  timeout_seconds: number
  anthropic_fallbacks: boolean
  daily_token_budget: number | null
  enabled: boolean
  activate: boolean
}

/** 测试 / 拉取模型列表：传 id 用已保存配置（Key 留空），否则用临时配置 */
export interface LlmProbeIn extends Omit<LlmProviderIn, 'enabled' | 'activate' | 'daily_token_budget'> {
  id?: number
}

export interface LlmStatus {
  active_source: string
  using_env: boolean
  config: {
    kind: LlmKind
    base_url: string
    model_vision: string
    model_chat: string
    model_fast: string
  }
  gateway: {
    available: boolean
    provider: string
    source: string
    error: string | null
    models: Record<string, string>
    usage_today: { calls: number; input_tokens: number; output_tokens: number; budget: number }
  }
}

export const getLlmMeta = () => http.get<LlmMeta>('/llm/meta').then((r) => r.data)
export const getLlmStatus = () => http.get<LlmStatus>('/llm/status').then((r) => r.data)
export const listLlmProviders = () => http.get<LlmProvider[]>('/llm/providers').then((r) => r.data)
export const createLlmProvider = (body: LlmProviderIn) =>
  http.post<LlmProvider>('/llm/providers', body).then((r) => r.data)
export const updateLlmProvider = (id: number, body: Partial<LlmProviderIn>) =>
  http.patch<LlmProvider>(`/llm/providers/${id}`, body).then((r) => r.data)
export const activateLlmProvider = (id: number) =>
  http.post<LlmProvider>(`/llm/providers/${id}/activate`).then((r) => r.data)
export const deleteLlmProvider = (id: number) => http.delete(`/llm/providers/${id}`)
export const testLlmProvider = (body: LlmProbeIn) =>
  http.post<{ ok: boolean; message: string; model: string }>('/llm/test', body, { timeout: 120_000 }).then((r) => r.data)
export const fetchLlmModels = (body: LlmProbeIn) =>
  http.post<{ models: string[] }>('/llm/models', body, { timeout: 60_000 }).then((r) => r.data)
