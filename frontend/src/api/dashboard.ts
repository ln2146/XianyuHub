import { http } from './http'

export interface DashboardAccount {
  id: number
  unb?: string
  nickname: string
  remark?: string | null
  avatar?: string | null
  status: string
  health: number
  im_connected: boolean
  auto_reply: boolean
  auto_delivery: boolean
}

export interface LlmStatus {
  available: boolean
  provider: string
  /** 生效配置来源：接入名称，或 env 表示回退到环境变量 */
  source: string
  error: string | null
  models: Record<string, string>
  usage_today: { calls: number; input_tokens: number; output_tokens: number; budget: number }
}

export interface Dashboard {
  accounts: DashboardAccount[]
  today: {
    messages_in: number
    messages_auto: number
    messages_manual: number
    deliveries: number
    orders: Record<string, number>
    gmv: number
    radar: Record<string, number>
  }
  pending_manual_orders: number
  monitor_tasks: number
  risk_events: {
    id: number
    account_id: number | null
    punish_url: string | null
    state: string; reason: string; created_at: string; resolved: boolean }[]
  system: {
    llm: LlmStatus
    im_running: boolean
    jobs: { id: string; next_run: string | null }[]
  }
}

export const getDashboard = () => http.get<Dashboard>('/dashboard').then((r) => r.data)
