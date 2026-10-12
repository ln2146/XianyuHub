import { ElMessage } from 'element-plus'

type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'

/** 安全解析日期：确保后端返回的 UTC ISO 串能被正确解析为本地时间，即使缺少 Z 时区后缀 */
export function parseDate(v: string | number | Date | null | undefined): Date | null {
  if (!v) return null
  if (v instanceof Date) return Number.isNaN(v.getTime()) ? null : v
  if (typeof v === 'number') return new Date(v)
  let s = String(v).trim()
  if (!s) return null
  // 如果字符串没有时区后缀（没有 Z 也没有 +08:00 / -05:00），且符合日期格式
  // 后端一律按 UTC 存储，因此补上 Z，避免被浏览器当成本地时间解析导致 8 小时时差
  if (!s.endsWith('Z') && !/[+-]\d{2}(?::?\d{2})?$/.test(s)) {
    s = s.replace(' ', 'T') + 'Z'
  }
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? null : d
}

/** 时间格式化：后端返回 ISO（UTC），显示为本地时间 */
export function fmtTime(v: string | number | Date | null | undefined, withSeconds = false): string {
  if (!v) return '-'
  const d = parseDate(v)
  if (!d) return String(v)
  const p = (n: number) => String(n).padStart(2, '0')
  const base = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
  return withSeconds ? `${base}:${p(d.getSeconds())}` : base
}

/** 相对时间：刚刚 / 5 分钟前 / 3 小时前 / 日期 */
export function fmtRelative(v: string | number | Date | null | undefined): string {
  if (!v) return ''
  const d = parseDate(v)
  if (!d) return ''
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 0 && diff > -60) return '刚刚'
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
  cooldown: { label: '暂停保护中', type: 'warning' },
  circuit_open: { label: '被平台限制', type: 'danger' },
  need_login: { label: '需重新登录', type: 'danger' },
  disabled: { label: '已停用', type: 'info' },
}

export const verdictMap: Record<string, { label: string; type: TagType }> = {
  recommend: { label: '推荐', type: 'success' },
  conditional: { label: '需核验', type: 'warning' },
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

/** 需要卖家处理的订单状态（与后端总览 pending_manual_orders 的统计口径一致） */
export const NEEDS_ACTION_STATUSES = 'manual,risk_hold,deliver_failed'

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
  unknown: { label: '发布结果未知', type: 'warning' },
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
  item_relisted: '卖完自动重新上架',
}

export const notifyTypeMap: Record<string, string> = {
  serverchan: '微信服务号（Server酱）',
  pushplus: '微信公众号（PushPlus）',
  wecom: '企业微信',
  feishu: '飞书',
  dingtalk: '钉钉',
  telegram: 'Telegram',
  bark: 'Bark (iOS)',
  ntfy: 'ntfy',
  webhook: '自定义 Webhook',
  email: 'QQ邮箱 / 常用邮箱',
}

/** 复制提问并打开闲鱼商品页：到闲鱼里点「我想要」进入聊天，直接粘贴发送 */
export async function askSellerOnGoofish(questions: string[], link: string) {
  // 先在当前页仍有焦点时发起复制，再同步打开新页面（避免剪贴板失败或被当作弹窗拦截）
  const copying = navigator.clipboard?.writeText(questions.join('\n'))
  window.open(link, '_blank', 'noopener')
  try {
    await copying
    ElMessage.success('提问已复制：在闲鱼商品页点「我想要」进入聊天后粘贴发送')
  } catch {
    ElMessage.warning('已打开闲鱼商品页；复制失败，请回到这里点「复制全部」')
  }
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

/** 闲鱼接口错误码 → 用户能看懂的说明（原文放在悬浮提示里） */
const GOOFISH_ERRORS: [RegExp, string][] = [
  [/SESSION_EXPIRED|FAIL_SYS_LOGIN|NOT_LOGIN/i, '登录已过期，需要重新登录'],
  [/RGV587|USER_VALIDATE|punish|滑块/i, '触发闲鱼风控，需要到闲鱼完成验证'],
  [/TOKEN_EXOIRED|TOKEN_EXPIRED|TOKEN_EMPTY/i, '登录凭证需要刷新，稍后会自动重试'],
  [/FLOW_LIMIT|被挤爆|请稍后重试/i, '闲鱼临时限流，稍后会自动恢复'],
]

export function friendlyError(raw: string | null | undefined): string {
  if (!raw) return ''
  for (const [re, text] of GOOFISH_ERRORS) if (re.test(raw)) return text
  // 「CODE::说明」只保留说明
  const m = raw.match(/^[A-Z0-9_]+::(.+)$/)
  return m ? m[1] : raw
}

/** 买家消息意图（后端 Intent） */
export const intentMap: Record<string, string> = {
  bargain: '议价',
  product: '商品咨询',
  logistics: '发货 / 物流',
  after_sale: '售后 / 投诉',
  greeting: '打招呼',
  no_reply: '无需回复',
  other: '其他',
}
export const intentText = (v: string | null | undefined) => (v ? intentMap[v] || v : '')
