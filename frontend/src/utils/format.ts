import { ElMessage } from 'element-plus'

type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'

/** 时间格式化：后端返回 ISO（UTC），显示为本地时间 */
export function fmtTime(v: string | null | undefined, withSeconds = false): string {
  if (!v) return '-'
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return v
  const p = (n: number) => String(n).padStart(2, '0')
  const base = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
  return withSeconds ? `${base}:${p(d.getSeconds())}` : base
}

/** 相对时间：刚刚 / 5 分钟前 / 3 小时前 / 日期 */
export function fmtRelative(v: string | null | undefined): string {
  if (!v) return ''
  const d = new Date(v)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`
  return fmtTime(v).slice(0, 10)
}

export function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined) return '-'
  return `¥${Number(v).toFixed(2).replace(/\.00$/, '')}`
}

export const accountStatusMap: Record<string, { label: string; type: TagType }> = {
  active: { label: '正常', type: 'success' },
  cooldown: { label: '冷却中', type: 'warning' },
  circuit_open: { label: '风控熔断', type: 'danger' },
  need_login: { label: '需重新登录', type: 'info' },
  disabled: { label: '已停用', type: 'info' },
}

export const verdictMap: Record<string, { label: string; type: TagType }> = {
  recommend: { label: '推荐', type: 'success' },
  conditional: { label: '有条件推荐', type: 'warning' },
  reject: { label: '不推荐', type: 'danger' },
  filtered: { label: '已筛除', type: 'info' },
}

export const markMap: Record<string, string> = {
  none: '未标记',
  favorite: '收藏',
  seen: '已看',
  ignored: '不感兴趣',
  bought: '已买',
}

export const orderStatusMap: Record<string, { label: string; type: TagType }> = {
  pending_pay: { label: '待付款', type: 'info' },
  paid: { label: '已付款', type: 'primary' },
  risk_hold: { label: '风控暂停', type: 'danger' },
  delivering: { label: '发货中', type: 'primary' },
  delivered: { label: '已发货', type: 'success' },
  deliver_failed: { label: '发货失败', type: 'danger' },
  manual: { label: '待人工', type: 'warning' },
  completed: { label: '已完成', type: 'success' },
  refunding: { label: '退款中', type: 'warning' },
  refunded: { label: '已退款', type: 'info' },
  closed: { label: '已关闭', type: 'info' },
}

export const goodsStatusMap: Record<string, { label: string; type: TagType }> = {
  on_sale: { label: '在售', type: 'success' },
  sold: { label: '已售出', type: 'info' },
  offline: { label: '已下架', type: 'warning' },
}

export const draftStatusMap: Record<string, { label: string; type: TagType }> = {
  draft: { label: '草稿', type: 'info' },
  scheduled: { label: '定时发布', type: 'primary' },
  publishing: { label: '发布中', type: 'warning' },
  published: { label: '已发布', type: 'success' },
  failed: { label: '失败', type: 'danger' },
}

/** 消息来源：标签 + 气泡配色 */
export const sourceMap: Record<string, { label: string; type: TagType; cls: string }> = {
  buyer: { label: '买家', type: 'info', cls: 'src-buyer' },
  seller_app: { label: '卖家 App', type: 'primary', cls: 'src-manual' },
  web_manual: { label: '人工', type: 'primary', cls: 'src-manual' },
  auto_keyword: { label: '关键词', type: 'warning', cls: 'src-keyword' },
  auto_ai: { label: 'AI', type: 'success', cls: 'src-ai' },
  auto_default: { label: '默认回复', type: 'warning', cls: 'src-keyword' },
  delivery: { label: '自动发货', type: 'success', cls: 'src-delivery' },
  system: { label: '系统', type: 'info', cls: 'src-system' },
}

export const roleMap: Record<string, string> = { admin: '管理员', operator: '运营', member: '成员' }

export const notifyEventMap: Record<string, string> = {
  item_recommended: '选品推荐',
  price_drop: '降价提醒',
  account_risk: '账号风控',
  account_login_required: '账号需重新登录',
  new_message: '新买家消息',
  human_handoff: '转人工',
  order_paid: '订单付款',
  delivery_failed: '发货失败',
  stock_low: '库存不足',
  task_failed: '任务失败',
}

export const notifyTypeMap: Record<string, string> = {
  wecom: '企业微信',
  feishu: '飞书',
  dingtalk: '钉钉',
  telegram: 'Telegram',
  bark: 'Bark',
  ntfy: 'ntfy',
  webhook: 'Webhook',
  email: '邮件',
}

export async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    // 非 https 环境下 clipboard API 不可用，降级为 execCommand
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy')
      ElMessage.success('已复制')
    } catch {
      ElMessage.error('复制失败')
    }
    ta.remove()
  }
}

/** 闲鱼商品详情页链接 */
export function itemUrl(itemId: string | null | undefined): string {
  return `https://www.goofish.com/item?id=${itemId ?? ''}`
}
