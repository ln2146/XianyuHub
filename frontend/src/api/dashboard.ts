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
    paid_orders: number
    paid_amount: number
    payment_basis: string
    unknown_payment_orders: number
    radar: Record<string, number>
  }
  pending_manual_orders: number
  /** 已付款未发出的订单数（含发货失败、风控暂停、待人工） */
  to_ship: number
  /** 近 7 天（含今天）每日付款金额与订单数 */
  trend: { date: string; amount: number; orders: number }[]
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

export const getDashboard = () => http.get<Dashboard>('/dashboard', { silent: true }).then((r) => r.data)
