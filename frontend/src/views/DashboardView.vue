<script setup lang="ts">
// 总览：商家每天打开先看的一页——要处理什么、生意怎么样、AI 帮我做了多少、最近订单和咨询、哪些商品受欢迎。
// 模型、长连接、调度等运行细节不在这里展示。
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Box, ChatDotRound, Plus, Search, Star, User, View, Warning } from '@element-plus/icons-vue'
import EChart from '@/components/EChart.vue'
import { getDashboard, type Dashboard, type DashboardAccount } from '@/api/dashboard'
import { updateAccount } from '@/api/account'
import { listOrders, type Order } from '@/api/order'
import { listConversations, type Conversation } from '@/api/message'
import { listItems, type MyItem } from '@/api/goods'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useRealtimeStore } from '@/stores/realtime'
import { usePrefsStore } from '@/stores/prefs'
import { NEEDS_ACTION_STATUSES, fmtMoney, fmtRelative, orderStatusMap } from '@/utils/format'

defineOptions({ name: 'DashboardView' })

const router = useRouter()
const auth = useAuthStore()
const realtime = useRealtimeStore()
const prefs = usePrefsStore()

const data = ref<Dashboard | null>(null)
const recentOrders = ref<Order[]>([])
const recentChats = ref<Conversation[]>([])
const items = ref<MyItem[]>([])
const loaded = ref(false)
let loading = false

const TO_SHIP_STATUSES = `paid,${NEEDS_ACTION_STATUSES}`

async function load() {
  if (loading) return
  loading = true
  const seller = prefs.showSeller
  try {
    const [dash, orders, chats, goods] = await Promise.all([
      getDashboard(),
      seller ? listOrders({ limit: 5 }).then((r) => r.items).catch(() => recentOrders.value) : [],
      seller ? listConversations({ limit: 5 }).then((r) => r.items).catch(() => recentChats.value) : [],
      seller ? listItems({}).catch(() => items.value) : [],
    ])
    data.value = dash
    recentOrders.value = orders
    recentChats.value = chats
    items.value = goods
  } catch {
    /* 静默：保留上一次的数据，下一轮自动重试 */
  } finally {
    loading = false
    loaded.value = true
  }
}

let timer: number | undefined
let debounce: number | undefined
let unsubscribe: (() => void) | undefined
onMounted(() => {
  load()
  timer = window.setInterval(load, 60_000)
  unsubscribe = realtime.subscribe((ev) => {
    if (['account', 'order', 'message'].includes(ev.event)) {
      window.clearTimeout(debounce)
      debounce = window.setTimeout(load, 1500)
    }
  })
})
onBeforeUnmount(() => {
  window.clearInterval(timer)
  window.clearTimeout(debounce)
  unsubscribe?.()
})

// ---------- 页头 ----------
const greeting = computed(() => {
  const h = new Date().getHours()
  const part = h < 6 ? '夜深了' : h < 11 ? '早上好' : h < 13 ? '中午好' : h < 18 ? '下午好' : '晚上好'
  return `${part}，${auth.user?.username || ''}`
})
const today = computed(() => {
  const d = new Date()
  return `${d.getMonth() + 1}月${d.getDate()}日 周${['日', '一', '二', '三', '四', '五', '六'][d.getDay()]}`
})

function accountLabel(a: DashboardAccount) {
  return a.remark || a.nickname || `账号 ${a.id}`
}

// ---------- 待办 ----------
const abnormalAccounts = computed(() =>
  (data.value?.accounts || []).filter(
    (a) => ['need_login', 'circuit_open'].includes(a.status) || (a.status === 'active' && !a.im_connected),
  ),
)

function goAbnormal() {
  const a = abnormalAccounts.value.find((x) => x.status === 'need_login')
  router.push(a ? { path: '/accounts', query: { relogin: String(a.id) } } : '/accounts')
}

const tiles = computed(() => {
  const d = data.value
  if (!prefs.showSeller) {
    return [
      { key: 'rec', label: '今日推荐好货', value: d?.today.radar.recommend || 0, tone: 'brand', icon: Star, go: () => router.push('/radar/smart') },
      { key: 'check', label: '需要核验', value: d?.today.radar.conditional || 0, tone: 'warn', icon: Search, go: () => router.push('/radar/smart') },
      { key: 'subs', label: '搜索订阅', value: d?.monitor_tasks || 0, tone: 'brand', icon: View, go: () => router.push('/radar/smart') },
      { key: 'acct', label: '账号异常', value: abnormalAccounts.value.length, tone: 'bad', icon: User, go: goAbnormal },
    ]
  }
  return [
    {
      key: 'ship',
      label: '待发货',
      value: d?.to_ship || 0,
      tone: 'warn',
      icon: Box,
      go: () => router.push({ path: '/orders/list', query: { status: TO_SHIP_STATUSES } }),
    },
    { key: 'unread', label: '未读消息', value: realtime.totalUnread, tone: 'warn', icon: ChatDotRound, go: () => router.push('/messages/inbox') },
    {
      key: 'fail',
      label: '发货异常',
      value: d?.pending_manual_orders || 0,
      tone: 'bad',
      icon: Warning,
      go: () => router.push({ path: '/orders/list', query: { status: NEEDS_ACTION_STATUSES } }),
    },
    { key: 'acct', label: '账号异常', value: abnormalAccounts.value.length, tone: 'bad', icon: User, go: goAbnormal },
  ]
})

// 账号异常要说清楚是哪个、怎么办，单独给一条提示
const accountAlerts = computed(() =>
  abnormalAccounts.value.map((a) => {
    if (a.status === 'need_login') {
      return {
        id: a.id,
        text: `${accountLabel(a)} 登录已失效，登录前不会自动回复和发货`,
        action: '重新登录',
        go: () => router.push({ path: '/accounts', query: { relogin: String(a.id) } }),
      }
    }
    if (a.status === 'circuit_open') {
      const punish = data.value?.risk_events.find((r) => r.account_id === a.id && !r.resolved && r.punish_url)?.punish_url
      return {
        id: a.id,
        text: `${accountLabel(a)} 被闲鱼限制${punish ? '，需要在闲鱼完成验证' : ''}`,
        action: punish ? '去验证' : '查看',
        go: () => (punish ? window.open(punish, '_blank', 'noopener') : router.push('/accounts')),
      }
    }
    return { id: a.id, text: `${accountLabel(a)} 掉线了，暂时收不到买家消息，正在自动重连`, action: '查看', go: () => router.push('/accounts') }
  }),
)

// ---------- 经营数据 ----------
const yesterday = computed(() => {
  const t = data.value?.trend
  return t && t.length >= 2 ? t[t.length - 2] : undefined
})

function compare(now: number, before: number | undefined, money = false) {
  // 两天都没有数据时不比较，避免一行没有信息量的「持平」
  if (before === undefined || (now === 0 && before === 0)) return null
  const delta = now - before
  if (delta === 0) return { text: '与昨日持平', dir: 'flat' }
  const abs = money ? fmtMoney(Math.abs(delta)) : String(Math.abs(delta))
  return { text: `较昨日 ${delta > 0 ? '+' : '-'}${abs}`, dir: delta > 0 ? 'up' : 'down' }
}

const metrics = computed(() => {
  const t = data.value?.today
  return [
    { label: '成交额', value: fmtMoney(t?.paid_amount ?? 0), cmp: t ? compare(t.paid_amount, yesterday.value?.amount, true) : null },
    { label: '付款订单', value: String(t?.paid_orders ?? 0), cmp: t ? compare(t.paid_orders, yesterday.value?.orders) : null },
    { label: '买家咨询', value: String(t?.messages_in ?? 0), cmp: null },
    { label: '客单价', value: t && t.paid_orders ? fmtMoney(t.paid_amount / t.paid_orders) : '—', cmp: null },
  ]
})

const chartMetric = ref<'amount' | 'orders'>('amount')
const chartOptions = [
  { label: '成交额', value: 'amount' },
  { label: '订单数', value: 'orders' },
]
const weekTotal = computed(() => (data.value?.trend || []).reduce((s, d) => s + d.amount, 0))
const weekOrders = computed(() => (data.value?.trend || []).reduce((s, d) => s + d.orders, 0))

function token(name: string, fallback: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

const trendOption = computed(() => {
  const rows = data.value?.trend || []
  const isAmount = chartMetric.value === 'amount'
  const primary = token('--xh-primary', '#1e9e6a')
  const muted = token('--xh-muted', '#8a919f')
  const border = token('--xh-border', '#e8ebf0')
  const values = rows.map((r) => (isAmount ? r.amount : r.orders))
  // 全是 0 时固定一个整数刻度，避免出现 0.3、0.6 这类没意义的小数轴
  const emptyMax = values.every((v) => v === 0) ? (isAmount ? 100 : 4) : undefined
  return {
    grid: { left: 4, right: 12, top: 20, bottom: 0, containLabel: true },
    tooltip: {
      trigger: 'axis',
      formatter: (ps: { dataIndex: number }[]) => {
        const r = rows[ps[0]?.dataIndex ?? 0]
        return r ? `${r.date.slice(5).replace('-', '/')}<br/>成交额 ${fmtMoney(r.amount)}<br/>订单 ${r.orders} 笔` : ''
      },
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: rows.map((r, i) => (i === rows.length - 1 ? '今天' : r.date.slice(5).replace('-', '/'))),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: border } },
      axisLabel: { color: muted },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      max: emptyMax,
      interval: emptyMax ? emptyMax / 4 : undefined,
      splitNumber: 4,
      axisLabel: { color: muted, formatter: (v: number) => (isAmount ? `¥${v}` : `${v}`) },
      splitLine: { lineStyle: { color: border, type: 'dashed' } },
    },
    series: [
      {
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        data: values,
        lineStyle: { color: primary, width: 2 },
        itemStyle: { color: primary },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: `${primary}33` },
              { offset: 1, color: `${primary}00` },
            ],
          },
        },
      },
    ],
  }
})

// ---------- 智能托管 ----------
const autoStats = computed(() => {
  const t = data.value?.today
  const auto = t?.messages_auto || 0
  const manual = t?.messages_manual || 0
  const total = auto + manual
  return { auto, manual, deliveries: t?.deliveries || 0, rate: total ? Math.round((auto / total) * 100) : null }
})

const busy = reactive<Record<string, boolean>>({})
async function toggle(a: DashboardAccount, key: 'auto_reply' | 'auto_delivery', val: boolean) {
  const id = `${key}-${a.id}`
  busy[id] = true
  try {
    await updateAccount(a.id, { settings: { [key]: val } })
    a[key] = val
    ElMessage.success(`${key === 'auto_reply' ? '自动回复' : '自动发货'}已${val ? '开启' : '关闭'}`)
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[id] = false
  }
}

function accountState(a: DashboardAccount) {
  if (a.status === 'need_login') return { label: '需重新登录', dot: 'bad' }
  if (a.status === 'circuit_open') return { label: '被限制', dot: 'bad' }
  if (a.status === 'cooldown') return { label: '暂停保护中', dot: 'warn' }
  if (a.status === 'disabled') return { label: '已停用', dot: '' }
  return a.im_connected ? { label: '在线', dot: 'ok' } : { label: '掉线', dot: 'warn' }
}

// ---------- 最近订单 / 咨询 ----------
const itemById = computed(() => new Map(items.value.map((i) => [i.item_id, i])))

const dotOf: Record<string, string> = { success: 'ok', warning: 'warn', danger: 'bad', primary: 'warn', info: '' }
function orderStatus(o: Order) {
  // 已付款但未发出 = 待发货，用商家熟悉的说法
  if (o.status === 'paid') return { label: '待发货', dot: 'warn' }
  const m = orderStatusMap[o.status]
  return { label: m?.label || o.status, dot: dotOf[m?.type || 'info'] ?? '' }
}

// ---------- 商品 ----------
const goodsCount = computed(() => ({
  onSale: items.value.filter((i) => i.status === 'on_sale').length,
  sold: items.value.filter((i) => i.status === 'sold').length,
}))
const hotItems = computed(() =>
  items.value
    .filter((i) => i.status === 'on_sale')
    .sort((a, b) => (b.want_cnt || 0) - (a.want_cnt || 0) || (b.browse_cnt || 0) - (a.browse_cnt || 0))
    .slice(0, 4),
)
</script>

<template>
  <div class="dash">
    <header class="dash-head">
      <div>
        <h2>{{ greeting }}</h2>
        <p class="date">{{ today }}</p>
      </div>
      <div class="head-actions">
        <el-button v-if="prefs.showBuyer" :icon="Search" @click="router.push('/radar/smart')">选品雷达</el-button>
        <el-button v-if="prefs.showSeller" type="primary" :icon="Plus" @click="router.push('/goods/publish')">发布商品</el-button>
      </div>
    </header>

    <el-skeleton v-if="!loaded" :rows="10" animated />

    <template v-else>
      <!-- 待办 -->
      <section class="tiles">
        <button
          v-for="t in tiles"
          :key="t.key"
          type="button"
          class="tile"
          :class="[t.tone, { active: t.value > 0 }]"
          @click="t.go"
        >
          <span class="tile-icon"><el-icon><component :is="t.icon" /></el-icon></span>
          <span class="tile-body">
            <span class="tile-label">{{ t.label }}</span>
            <span class="tile-value">{{ t.value }}</span>
          </span>
          <el-icon class="tile-go"><ArrowRight /></el-icon>
        </button>
      </section>

      <div v-if="accountAlerts.length" class="alerts">
        <div v-for="a in accountAlerts" :key="a.id" class="alert">
          <el-icon class="alert-icon"><Warning /></el-icon>
          <span class="alert-text">{{ a.text }}</span>
          <el-button size="small" type="danger" plain @click="a.go">{{ a.action }}</el-button>
        </div>
      </div>

      <div class="grid-main" :class="{ single: !prefs.showSeller }">
        <!-- 经营数据 -->
        <section v-if="prefs.showSeller" class="card">
          <div class="card-head">
            <h3>今日经营</h3>
          </div>
          <div class="metrics">
            <div v-for="m in metrics" :key="m.label" class="metric">
              <span class="metric-label">{{ m.label }}</span>
              <span class="metric-value">{{ m.value }}</span>
              <span v-if="m.cmp" class="cmp" :class="m.cmp.dir">{{ m.cmp.text }}</span>
            </div>
          </div>
          <div class="chart-head">
            <span class="chart-title">近 7 天</span>
            <span class="chart-sum">{{ fmtMoney(weekTotal) }} · {{ weekOrders }} 笔</span>
            <el-segmented v-model="chartMetric" size="small" :options="chartOptions" />
          </div>
          <EChart :option="trendOption" height="200px" />
        </section>

        <!-- 智能托管 + 账号 -->
        <section class="card">
          <div class="card-head">
            <h3>{{ prefs.showSeller ? '智能托管' : '闲鱼账号' }}</h3>
            <router-link to="/accounts" class="more">账号管理<el-icon><ArrowRight /></el-icon></router-link>
          </div>
          <div v-if="prefs.showSeller" class="auto">
            <div class="auto-rate">
              <el-progress
                type="circle"
                :width="76"
                :stroke-width="7"
                :percentage="autoStats.rate ?? 0"
                :show-text="false"
                color="var(--xh-primary)"
              />
              <span class="rate-num">{{ autoStats.rate === null ? '—' : `${autoStats.rate}%` }}</span>
            </div>
            <div class="auto-list">
              <div class="auto-title">今日自动接待率</div>
              <div class="auto-row"><span>AI 自动回复</span><b>{{ autoStats.auto }} 条</b></div>
              <div class="auto-row"><span>人工回复</span><b>{{ autoStats.manual }} 条</b></div>
              <div class="auto-row"><span>自动发货</span><b>{{ autoStats.deliveries }} 单</b></div>
            </div>
          </div>

          <div class="accts">
            <div v-for="a in data?.accounts || []" :key="a.id" class="acct">
              <div class="acct-top">
                <el-avatar :size="36" :src="a.avatar || undefined" class="acct-av">{{ accountLabel(a).slice(0, 1) }}</el-avatar>
                <div class="acct-name">
                  <div class="ellipsis">{{ accountLabel(a) }}</div>
                  <div class="state"><span class="dot" :class="accountState(a).dot" />{{ accountState(a).label }}</div>
                </div>
                <div class="health">
                  <span>健康度</span>
                  <b>{{ a.health }}%</b>
                </div>
              </div>
              <div v-if="prefs.showSeller" class="acct-sw">
                <label>
                  <span>自动回复</span>
                  <el-switch
                    size="small"
                    :model-value="a.auto_reply"
                    :loading="busy[`auto_reply-${a.id}`]"
                    @change="(v: string | number | boolean) => toggle(a, 'auto_reply', !!v)"
                  />
                </label>
                <label>
                  <span>自动发货</span>
                  <el-switch
                    size="small"
                    :model-value="a.auto_delivery"
                    :loading="busy[`auto_delivery-${a.id}`]"
                    @change="(v: string | number | boolean) => toggle(a, 'auto_delivery', !!v)"
                  />
                </label>
              </div>
            </div>
            <div v-if="!data?.accounts.length" class="empty">
              <p>还没有接入闲鱼账号</p>
              <el-button type="primary" @click="router.push('/accounts')">添加账号</el-button>
            </div>
          </div>
        </section>
      </div>

      <div v-if="prefs.showSeller" class="grid-two">
        <!-- 最近订单 -->
        <section class="card flush">
          <div class="card-head pad">
            <h3>最近订单</h3>
            <router-link to="/orders/list" class="more">全部<el-icon><ArrowRight /></el-icon></router-link>
          </div>
          <div
            v-for="o in recentOrders"
            :key="o.id"
            class="line"
            @click="router.push({ path: '/orders/list', query: { q: o.order_id } })"
          >
            <el-image class="thumb" :src="itemById.get(o.item_id || '')?.image_url" fit="cover" referrerpolicy="no-referrer">
              <template #error><span class="thumb-ph"><el-icon><Box /></el-icon></span></template>
            </el-image>
            <div class="line-main">
              <div class="line-title ellipsis">{{ o.item_title || '未命名商品' }}</div>
              <div class="line-sub ellipsis">{{ o.buyer_nick || '买家' }} · {{ fmtRelative(o.actual_paid_at || o.created_at) }}</div>
            </div>
            <div class="line-end">
              <span class="price">{{ fmtMoney(o.amount) }}</span>
              <span class="state"><span class="dot" :class="orderStatus(o).dot" />{{ orderStatus(o).label }}</span>
            </div>
          </div>
          <div v-if="!recentOrders.length" class="empty">还没有订单</div>
        </section>

        <!-- 最近咨询 -->
        <section class="card flush">
          <div class="card-head pad">
            <h3>最近咨询</h3>
            <router-link to="/messages/inbox" class="more">全部<el-icon><ArrowRight /></el-icon></router-link>
          </div>
          <div
            v-for="c in recentChats"
            :key="c.id"
            class="line"
            @click="router.push({ path: '/messages/inbox', query: { conv: String(c.id) } })"
          >
            <el-badge :value="c.unread" :hidden="!c.unread" :max="99">
              <el-avatar :size="44" class="chat-av">{{ (c.peer_name || '买').slice(0, 1) }}</el-avatar>
            </el-badge>
            <div class="line-main">
              <div class="line-title ellipsis">{{ c.peer_name || '买家' }}</div>
              <div class="line-sub ellipsis">{{ c.last_message || '—' }}</div>
            </div>
            <div class="line-end">
              <span class="time">{{ fmtRelative(c.last_message_at) }}</span>
              <span v-if="c.in_takeover" class="takeover">人工接管</span>
            </div>
          </div>
          <div v-if="!recentChats.length" class="empty">还没有买家咨询</div>
        </section>
      </div>

      <!-- 我的商品 -->
      <section v-if="prefs.showSeller" class="card">
        <div class="card-head">
          <h3>我的商品</h3>
          <span class="card-hint">在售 {{ goodsCount.onSale }} · 已售 {{ goodsCount.sold }}</span>
          <router-link to="/goods/items" class="more">商品管理<el-icon><ArrowRight /></el-icon></router-link>
        </div>
        <div v-if="hotItems.length" class="goods">
          <button
            v-for="g in hotItems"
            :key="g.id"
            type="button"
            class="good"
            @click="router.push({ path: '/goods/items', query: { q: g.title } })"
          >
            <el-image class="good-img" :src="g.image_url" fit="cover" referrerpolicy="no-referrer" lazy>
              <template #error><span class="thumb-ph"><el-icon><Box /></el-icon></span></template>
            </el-image>
            <span class="good-title">{{ g.title }}</span>
            <span class="good-foot">
              <span class="price">{{ fmtMoney(g.price) }}</span>
              <span class="good-stat">{{ g.want_cnt ?? 0 }} 想要 · {{ g.browse_cnt ?? 0 }} 浏览</span>
            </span>
          </button>
        </div>
        <div v-else class="goods-empty">
          <span>还没有在售商品，拍几张照片，AI 帮你写标题和定价</span>
          <el-button type="primary" plain :icon="Plus" @click="router.push('/goods/publish')">发布商品</el-button>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.dash {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-bottom: 24px;
}

/* 页头 */
.dash-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}
.dash-head h2 {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
}
.date {
  margin: 4px 0 0;
  color: var(--xh-muted);
  font-size: var(--xh-fs-md);
}
.head-actions {
  display: flex;
  gap: 8px;
}

/* 通用卡片 */
.card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-lg);
  padding: 20px;
  min-width: 0;
}
.card.flush {
  padding: 0 0 8px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.card-head.pad {
  padding: 20px 20px 0;
  margin-bottom: 8px;
}
.card-head h3 {
  margin: 0;
  font-size: var(--xh-fs-lg);
  font-weight: 600;
}
.card-hint {
  color: var(--xh-muted);
  font-size: var(--xh-fs-sm);
}
.more {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--xh-primary);
  font-size: var(--xh-fs-sm);
  text-decoration: none;
}
.empty {
  padding: 32px 16px;
  text-align: center;
  color: var(--xh-muted);
}
.empty p {
  margin: 0 0 12px;
}

/* 待办卡片 */
.tiles {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}
.tile {
  --tone: var(--xh-primary);
  --tone-soft: var(--xh-primary-soft);
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px;
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-lg);
  background: var(--xh-card);
  font: inherit;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}
.tile.warn {
  --tone: var(--xh-warning);
  --tone-soft: var(--el-color-warning-light-9);
}
.tile.bad {
  --tone: var(--xh-danger);
  --tone-soft: var(--el-color-danger-light-9);
}
.tile:hover {
  border-color: var(--xh-border-strong);
  box-shadow: var(--xh-shadow-2);
}
.tile-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  flex: none;
  background: var(--xh-fill);
  color: var(--xh-muted);
}
.tile.active .tile-icon,
.tile.brand .tile-icon {
  background: var(--tone-soft);
  color: var(--tone);
}
.tile-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.tile-label {
  color: var(--xh-text-2);
  font-size: var(--xh-fs-md);
}
.tile-value {
  font-size: var(--xh-fs-xxl);
  font-weight: 600;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
  color: var(--xh-text);
}
.tile.active:not(.brand) .tile-value {
  color: var(--tone);
}
.tile-go {
  color: var(--xh-disabled);
}

/* 账号提醒 */
.alerts {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.alert {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: var(--xh-radius-md);
  background: var(--el-color-danger-light-9);
  border: 1px solid var(--el-color-danger-light-7);
}
.alert-icon {
  color: var(--xh-danger);
  font-size: 18px;
}
.alert-text {
  flex: 1;
  min-width: 0;
}

/* 主区 */
.grid-main {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  gap: 16px;
}
.grid-main.single {
  grid-template-columns: minmax(0, 1fr);
}
.metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.metric {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px 16px;
  border-radius: var(--xh-radius-md);
  background: var(--xh-fill);
}
.metric-label {
  color: var(--xh-text-2);
  font-size: var(--xh-fs-sm);
}
.metric-value {
  font-size: 24px;
  font-weight: 600;
  line-height: 1.25;
  font-variant-numeric: tabular-nums;
}
.cmp {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}
.cmp.up {
  color: var(--xh-success);
}
.cmp.down {
  color: var(--xh-danger);
}
.chart-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 20px 0 4px;
}
.chart-title {
  font-weight: 600;
}
.chart-sum {
  flex: 1;
  color: var(--xh-muted);
  font-size: var(--xh-fs-sm);
  font-variant-numeric: tabular-nums;
}

/* 智能托管 */
.auto {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 16px;
  border-radius: var(--xh-radius-md);
  background: var(--xh-primary-soft);
  margin-bottom: 16px;
}
.auto-rate {
  position: relative;
  flex: none;
  display: flex;
}
.auto-rate :deep(.el-progress-circle__track) {
  stroke: var(--xh-primary-border);
}
.rate-num {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: var(--xh-fs-lg);
  color: var(--xh-primary);
}
.auto-list {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.auto-title {
  font-weight: 600;
  margin-bottom: 2px;
}
.auto-row {
  display: flex;
  justify-content: space-between;
  font-size: var(--xh-fs-sm);
  color: var(--xh-text-2);
}
.auto-row b {
  color: var(--xh-text);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.accts {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.acct {
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: 12px 14px;
}
.acct-top {
  display: flex;
  align-items: center;
  gap: 10px;
}
.acct-av {
  background: var(--xh-fill-strong);
  color: var(--xh-text-2);
  flex: none;
}
.acct-name {
  flex: 1;
  min-width: 0;
  font-weight: 500;
}
.health {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}
.health b {
  font-size: var(--xh-fs-md);
  color: var(--xh-text);
  font-weight: 600;
}
.acct-sw {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--xh-border);
}
.acct-sw label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: var(--xh-fs-sm);
  color: var(--xh-text-2);
  cursor: pointer;
}

/* 状态点：总是配文字 */
.state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--xh-fs-sm);
  color: var(--xh-text-2);
  font-weight: 400;
  white-space: nowrap;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--xh-disabled);
  flex: none;
  display: inline-block;
}
.dot.ok {
  background: var(--xh-success);
}
.dot.warn {
  background: var(--xh-warning);
}
.dot.bad {
  background: var(--xh-danger);
}

/* 列表 */
.grid-two {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
}
.line {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 20px;
  cursor: pointer;
}
.line:hover {
  background: var(--xh-fill);
}
.thumb {
  width: 44px;
  height: 44px;
  border-radius: var(--xh-radius-sm);
  flex: none;
  background: var(--xh-fill-strong);
}
.thumb-ph {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--xh-disabled);
  font-size: 20px;
  background: var(--xh-fill-strong);
}
.chat-av {
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
  font-weight: 600;
}
.line-main {
  flex: 1;
  min-width: 0;
}
.line-title {
  font-weight: 500;
}
.line-sub {
  color: var(--xh-muted);
  font-size: var(--xh-fs-sm);
  margin-top: 2px;
}
.line-end {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  flex: none;
}
.price {
  color: var(--xh-price);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.time {
  color: var(--xh-muted);
  font-size: var(--xh-fs-xs);
}
.takeover {
  font-size: var(--xh-fs-xs);
  color: var(--xh-warning-text);
}

/* 商品 */
.goods {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}
.good {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0;
  border: none;
  background: none;
  font: inherit;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.good-img {
  width: 100%;
  aspect-ratio: 1 / 1;
  border-radius: var(--xh-radius-md);
  background: var(--xh-fill-strong);
}
.good:hover .good-title {
  color: var(--xh-primary);
}
.good-title {
  font-size: var(--xh-fs-md);
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.good-foot {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.good-stat {
  color: var(--xh-muted);
  font-size: var(--xh-fs-xs);
  white-space: nowrap;
}
.goods-empty {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 16px 18px;
  border-radius: var(--xh-radius-md);
  background: var(--xh-fill);
  color: var(--xh-text-2);
}

@media (max-width: 1100px) {
  .tiles {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .grid-main,
  .grid-two {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 640px) {
  .tiles {
    gap: 10px;
  }
  .tile {
    padding: 14px;
    gap: 10px;
  }
  .tile-icon {
    width: 36px;
    height: 36px;
    font-size: 18px;
  }
  .tile-value {
    font-size: 22px;
  }
  .tile-go {
    display: none;
  }
  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .goods {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .card {
    padding: 16px;
  }
  .card.flush {
    padding: 0 0 8px;
  }
  .card-head.pad {
    padding: 16px 16px 0;
  }
  .line {
    padding: 10px 16px;
  }
}
</style>
