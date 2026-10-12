<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRealtimeStore } from '@/stores/realtime'
import { useRouter } from 'vue-router'
import {
  Box,
  ChatDotRound,
  CircleCheck,
  DataLine,
  InfoFilled,
  Lightning,
  Money,
  Plus,
  Promotion,
  Refresh,
  Right,
  Setting,
  Timer,
  Tools,
  Warning,
} from '@element-plus/icons-vue'
import { getDashboard, type Dashboard, type DashboardAccount } from '@/api/dashboard'
import { updateAccount } from '@/api/account'
import { errorMessage } from '@/api/http'
import { ElMessage } from 'element-plus'
import StatusTag from '@/components/StatusTag.vue'
import { NEEDS_ACTION_STATUSES, accountStatusMap, fmtMoney, fmtTime, parseDate } from '@/utils/format'
import { usePrefsStore } from '@/stores/prefs'

const router = useRouter()
const realtime = useRealtimeStore()
const prefs = usePrefsStore()
const data = ref<Dashboard | null>(null)
const loading = ref(false)
const loadError = ref('')
const lastUpdated = ref<Date | null>(null)
const monitoring = computed(() => !!data.value && !loadError.value && realtime.connected && data.value.system.im_running)
const monitoringText = computed(() =>
  loadError.value
    ? '数据未更新'
    : !data.value
      ? '状态待确认'
      : !realtime.connected
        ? '实时推送断开'
        : !data.value.system.im_running
          ? '消息服务未运行'
          : '实时已连接',
)
const activeTab = ref<'all' | 'accounts' | 'system'>('all')
let timer: number | undefined

async function load() {
  if (loading.value) return
  loading.value = true
  try {
    data.value = await getDashboard()
    loadError.value = ''
    lastUpdated.value = new Date()
  } catch (error) {
    loadError.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

const busy = reactive<Record<string, boolean>>({})

async function toggleAccountReply(row: DashboardAccount, val: boolean) {
  busy[`reply-${row.id}`] = true
  try {
    await updateAccount(row.id, { settings: { auto_reply: val } })
    row.auto_reply = val
    ElMessage.success(`账号「${row.nickname || row.id}」已${val ? '开启' : '关闭'}自动回复`)
  } catch {
    /* 拦截器已处理 */
  } finally {
    busy[`reply-${row.id}`] = false
  }
}

async function toggleAccountDelivery(row: DashboardAccount, val: boolean) {
  busy[`deliv-${row.id}`] = true
  try {
    await updateAccount(row.id, { settings: { auto_delivery: val } })
    row.auto_delivery = val
    ElMessage.success(`账号「${row.nickname || row.id}」已${val ? '开启' : '关闭'}自动发货`)
  } catch {
    /* 拦截器已处理 */
  } finally {
    busy[`deliv-${row.id}`] = false
  }
}

function goPendingOrders() {
  if ((data.value?.pending_manual_orders || 0) > 0) {
    router.push({ path: '/orders/list', query: { status: 'manual,risk_hold,deliver_failed' } })
  } else {
    router.push('/orders/list')
  }
}

let unsubscribe: (() => void) | undefined
let debounce: number | undefined
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

const kpis = computed(() => {
  const t = data.value?.today
  const radar = t ? (t.radar.recommend || 0) + (t.radar.conditional || 0) : 0
  const list = [
    {
      label: '今日买家消息',
      value: t?.messages_in ?? 0,
      hint: `人工已回 ${t?.messages_manual ?? 0} 条`,
      icon: ChatDotRound,
      color: '#059669',
      path: '/messages/inbox',
    },
    {
      label: '自动智能接待',
      value: t?.messages_auto ?? 0,
      hint: '全天候自动应答',
      icon: Lightning,
      color: '#059669',
      path: '/messages/rules',
    },
    {
      label: '自动发货卡密',
      value: t?.deliveries ?? 0,
      hint: '已发出卡密',
      icon: Promotion,
      color: '#059669',
      path: '/orders/cards',
    },
    {
      label: '今日付款订单',
      value: t?.paid_orders ?? 0,
      hint: '实付达成订单',
      icon: Box,
      color: '#d97706',
      path: '/orders/list',
    },
    {
      label: '今日付款金额',
      value: fmtMoney(t?.paid_amount ?? 0),
      hint: '买家实付总额',
      icon: Money,
      color: '#ea580c',
      path: '/orders/list',
    },
  ]
  if (prefs.showBuyer && radar > 0) {
    list.push({
      label: '选品好货推荐',
      value: radar,
      hint: `高契合好货`,
      icon: DataLine,
      color: '#0284c7',
      path: '/radar/smart',
    })
  }
  return list
})

const llm = computed(() => data.value?.system.llm)
const tokenUsed = computed(() => (llm.value ? llm.value.usage_today.input_tokens + llm.value.usage_today.output_tokens : 0))
const tokenPercent = computed(() => {
  const b = llm.value?.usage_today.budget || 0
  return b > 0 ? Math.min(100, Math.round((tokenUsed.value / b) * 100)) : 0
})

type DashAccount = NonNullable<typeof data.value>['accounts'][number]
const working = (a: DashAccount) => a.status === 'active' && a.im_connected
function switchState(on: (a: DashAccount) => boolean) {
  const list = data.value?.accounts.filter(on) || []
  if (!list.length) return { cls: 'off', text: '未开启' }
  const ok = list.filter(working).length
  if (ok === list.length) return { cls: 'online', text: '已开启' }
  return { cls: 'warn', text: ok ? `${list.length - ok} 个离线` : '未生效' }
}
const autoReplyState = computed(() => switchState((a) => a.auto_reply))
const autoDeliveryState = computed(() => switchState((a) => a.auto_delivery))
const autoReplyOn = computed(() => autoReplyState.value.cls === 'online')
const autoDeliveryOn = computed(() => autoDeliveryState.value.cls === 'online')
const restrictedCount = computed(
  () => data.value?.accounts.filter((a) => a.status !== 'disabled' && !working(a)).length || 0,
)
const firstNeedLoginAccount = computed(() =>
  data.value?.accounts.find((a) => a.status === 'need_login'),
)
function goAccounts() {
  if (firstNeedLoginAccount.value) {
    router.push({ path: '/accounts', query: { relogin: String(firstNeedLoginAccount.value.id) } })
  } else {
    router.push('/accounts')
  }
}
const imOnlineCount = computed(() => data.value?.accounts.filter((a) => a.im_connected).length || 0)

function accountName(id: number | null) {
  if (id === null) return '系统'
  return data.value?.accounts.find((a) => a.id === id)?.nickname || `#${id}`
}

function healthColor(h: number) {
  if (h >= 80) return 'var(--xh-success)'
  if (h >= 50) return 'var(--xh-warning)'
  return 'var(--xh-danger)'
}

interface JobMeta {
  title: string
  desc: string
  category: string
  tagType: 'success' | 'warning' | 'primary' | 'info'
}

const jobMetaMap: Record<string, JobMeta> = {
  'goods.publish_due': { title: '待发商品定时发布', desc: '按时自动发布已排期商品', category: '商品', tagType: 'primary' },
  'order.sync': { title: '订单数据实时同步', desc: '持续同步付款/退款状态', category: '订单', tagType: 'success' },
  'order.retry_failed': { title: '失败发货自动重试', desc: '异常订单自动重试卡密下发', category: '发货', tagType: 'warning' },
  'buyer.price_watch': { title: '关注商品降价监控', desc: '全天候轮询降价与到价预警', category: '监控', tagType: 'primary' },
  'account.keepalive': { title: '闲鱼账号心跳保活', desc: '保持闲鱼登录 Session 存活', category: '账号', tagType: 'info' },
  'goods.polish_all': { title: '全量商品每日擦亮', desc: '自动批量擦亮提升宝贝曝光', category: '商品', tagType: 'primary' },
}

function getJobMeta(id: string): JobMeta {
  if (jobMetaMap[id]) return jobMetaMap[id]
  if (id.startsWith('buyer.')) {
    const taskNum = id.replace(/^buyer\.task\.?/, '')
    return {
      title: taskNum ? `选品监控巡检 · #${taskNum}` : '选品降价监控巡检',
      desc: '定时轮询闲鱼好货与价格变动',
      category: '监控',
      tagType: 'primary',
    }
  }
  return {
    title: id,
    desc: '系统常规后台调度任务',
    category: '调度',
    tagType: 'info',
  }
}

function fmtJobNextRun(v: string | null | undefined): string {
  if (!v) return '就绪中'
  const d = parseDate(v)
  if (!d) return v
  const p = (n: number) => String(n).padStart(2, '0')
  const now = new Date()
  const isToday = d.toDateString() === now.toDateString()
  const timeStr = `${p(d.getHours())}:${p(d.getMinutes())}`
  return isToday ? `今日 ${timeStr}` : `${p(d.getMonth() + 1)}-${p(d.getDate())} ${timeStr}`
}
</script>

<template>
  <div v-loading="loading && !data" class="page dashboard-page">
    <!-- 极简顶部状态栏（去除多行文字喧宾夺主） -->
    <header class="dash-header">
      <div class="header-left">
        <h2 class="page-title-text">工作台总览</h2>
        <div class="live-status-pill" :class="{ off: !monitoring }">
          <span class="pulse-dot" />
          <span>{{ monitoringText }}</span>
        </div>
        <el-tooltip
          v-if="data?.today.payment_basis"
          :content="`统计口径：${data.today.payment_basis}。${data.today.unknown_payment_orders ? `${data.today.unknown_payment_orders} 笔订单无确切付款时间未纳入统计。` : ''}`"
          placement="top"
        >
          <span class="info-help-icon"><el-icon><InfoFilled /></el-icon></span>
        </el-tooltip>
      </div>

      <div class="header-right">
        <!-- 待办订单报警胶囊 -->
        <button
          v-if="data && (data.pending_manual_orders || 0) > 0"
          type="button"
          class="alert-capsule-btn warning"
          @click="router.push({ path: '/orders/list', query: { status: NEEDS_ACTION_STATUSES } })"
        >
          <el-icon class="icon"><Warning /></el-icon>
          <span>{{ data.pending_manual_orders }} 笔订单待处理</span>
          <el-icon class="arrow"><Right /></el-icon>
        </button>

        <button
          v-else-if="restrictedCount > 0"
          type="button"
          class="alert-capsule-btn danger"
          @click="goAccounts"
        >
          <el-icon class="icon"><Warning /></el-icon>
          <span>{{ restrictedCount }} 个账号需重新登录</span>
          <el-icon class="arrow"><Right /></el-icon>
        </button>

        <div class="sync-actions">
          <span v-if="lastUpdated && !loadError" class="last-sync-time">
            {{ lastUpdated.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}
          </span>
          <el-button :icon="Refresh" :loading="loading" size="small" class="refresh-btn" circle @click="load" />
        </div>
      </div>
    </header>

    <el-alert
      v-if="loadError"
      type="error"
      :title="loadError"
      :closable="false"
      show-icon
    >
      <template #default>
        <span v-if="lastUpdated">上次同步快照：{{ lastUpdated.toLocaleTimeString('zh-CN') }} · </span>
        <el-button link type="primary" size="small" @click="load">重试连接</el-button>
      </template>
    </el-alert>

    <template v-if="data">
      <!-- Stripe 风格 Executive KPI 纯净卡片流 -->
      <section class="kpi-grid">
        <div
          v-for="k in kpis"
          :key="k.label"
          class="kpi-card"
          @click="router.push(k.path)"
        >
          <div class="kpi-top">
            <span class="kpi-label">{{ k.label }}</span>
            <el-icon class="kpi-icon"><component :is="k.icon" /></el-icon>
          </div>
          <div class="kpi-value">{{ k.value }}</div>
          <div class="kpi-footer">
            <span class="kpi-hint">{{ k.hint }}</span>
          </div>
        </div>
      </section>

      <!-- 工作台分段导航与内容区 -->
      <main class="dash-main-area">
        <div class="dash-seg-control">
          <div class="seg-pills" role="tablist">
            <button
              type="button"
              class="seg-pill"
              :class="{ active: activeTab === 'all' }"
              @click="activeTab = 'all'"
            >
              全部大盘
            </button>
            <button
              type="button"
              class="seg-pill"
              :class="{ active: activeTab === 'accounts' }"
              @click="activeTab = 'accounts'"
            >
              账号与风控
              <span v-if="data.accounts.length" class="pill-badge">{{ data.accounts.length }}</span>
            </button>
            <button
              type="button"
              class="seg-pill"
              :class="{ active: activeTab === 'system' }"
              @click="activeTab = 'system'"
            >
              AI 与系统调度
            </button>
          </div>

          <div class="seg-meta">
            <span class="im-status-chip">
              <span class="chip-dot" :class="{ on: imOnlineCount > 0 }" />
              IM 消息长连接：{{ imOnlineCount }} / {{ data.accounts.length }} 在线
            </span>
          </div>
        </div>

        <div class="dash-panes">
          <!-- 账号与风控视图 -->
          <div v-show="activeTab === 'all' || activeTab === 'accounts'" class="dash-row two-col">
            <!-- 左侧：已接入闲鱼账号 -->
            <div class="dash-card accounts-card">
              <div class="card-head">
                <div class="head-title">
                  <span>已接入闲鱼账号</span>
                  <span class="count-tag">{{ data.accounts.length }}</span>
                </div>
                <div class="head-actions">
                  <el-button size="small" :icon="Plus" @click="router.push('/accounts')">接入账号</el-button>
                  <el-button size="small" type="primary" plain @click="router.push('/accounts')">管理</el-button>
                </div>
              </div>

              <div class="table-container">
                <el-table
                  :data="data.accounts"
                  size="small"
                  empty-text="暂无闲鱼账号，请前往账号配置添加"
                  max-height="250"
                >
                  <el-table-column label="账号" min-width="160">
                    <template #default="{ row }">
                      <div class="account-cell">
                        <div class="acc-avatar">
                          <img v-if="row.avatar" :src="row.avatar" alt="" referrerpolicy="no-referrer" />
                          <span v-else>{{ (row.remark || row.nickname || '闲')[0] }}</span>
                          <span class="dot-indicator" :class="row.im_connected ? 'online' : 'offline'" />
                        </div>
                        <div class="acc-info">
                          <div class="nick ellipsis">{{ row.remark || row.nickname || '闲鱼账号' }}</div>
                          <div class="unb mono">{{ row.unb ? `ID: ${row.unb}` : (row.remark ? row.nickname : '') }}</div>
                        </div>
                      </div>
                    </template>
                  </el-table-column>

                  <el-table-column label="状态" width="100">
                    <template #default="{ row }">
                      <StatusTag :value="row.status" :map="accountStatusMap" />
                    </template>
                  </el-table-column>

                  <el-table-column label="健康分" width="110">
                    <template #default="{ row }">
                      <div class="health-wrap">
                        <el-progress
                          :percentage="row.health"
                          :color="healthColor(row.health)"
                          :stroke-width="5"
                          :show-text="false"
                        />
                        <span class="health-num" :style="{ color: healthColor(row.health) }">{{ row.health }}%</span>
                      </div>
                    </template>
                  </el-table-column>

                  <el-table-column label="自动回复" width="85">
                    <template #default="{ row }">
                      <el-switch
                        :model-value="row.auto_reply"
                        :loading="busy[`reply-${row.id}`]"
                        inline-prompt
                        active-text="开"
                        inactive-text="关"
                        size="small"
                        @change="(v: string | number | boolean) => toggleAccountReply(row as DashboardAccount, !!v)"
                      />
                    </template>
                  </el-table-column>

                  <el-table-column label="自动发货" width="85">
                    <template #default="{ row }">
                      <el-switch
                        :model-value="row.auto_delivery"
                        :loading="busy[`deliv-${row.id}`]"
                        inline-prompt
                        active-text="开"
                        inactive-text="关"
                        size="small"
                        @change="(v: string | number | boolean) => toggleAccountDelivery(row as DashboardAccount, !!v)"
                      />
                    </template>
                  </el-table-column>
                </el-table>
              </div>

              <!-- 自动化极简效能统计 -->
              <div class="telemetry-bar">
                <div class="telemetry-item" @click="router.push('/messages/rules')">
                  <span class="t-label">自动回复</span>
                  <div class="t-data">
                    <span class="t-val">{{ data.today.messages_auto || 0 }}</span>
                    <span class="t-sub">{{ autoReplyState.text }}</span>
                  </div>
                </div>
                <div class="telemetry-item" @click="goPendingOrders">
                  <span class="t-label">自动发货</span>
                  <div class="t-data">
                    <span class="t-val">{{ data.today.deliveries || 0 }}</span>
                    <span class="t-sub">{{ autoDeliveryState.text }}</span>
                  </div>
                </div>
                <div class="telemetry-item" @click="goAccounts">
                  <span class="t-label">运行健康</span>
                  <div class="t-data">
                    <span class="t-val" :class="{ 'text-danger': restrictedCount > 0 }">
                      {{ data.accounts.length - restrictedCount }} / {{ data.accounts.length }}
                    </span>
                    <span class="t-sub">{{ restrictedCount ? `${restrictedCount}个需处理` : '全部正常' }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 右侧：待办中心 + 风控安全 -->
            <div class="right-stack">
              <!-- 待办事项快速卡片 -->
              <div class="dash-card pending-card" :class="{ alert: (data.pending_manual_orders || 0) > 0 }">
                <div class="pending-inner" @click="goPendingOrders">
                  <div class="pending-left">
                    <div class="status-icon" :class="(data.pending_manual_orders || 0) > 0 ? 'warning' : 'ok'">
                      <el-icon :size="20"><component :is="(data.pending_manual_orders || 0) > 0 ? Warning : CircleCheck" /></el-icon>
                    </div>
                    <div>
                      <div class="p-title">
                        {{ (data.pending_manual_orders || 0) > 0 ? `${data.pending_manual_orders} 笔订单待人工处理` : '订单履约通畅，无待办事项' }}
                      </div>
                      <div class="p-desc">
                        {{ (data.pending_manual_orders || 0) > 0 ? '包含缺卡、风控暂停或需人工核对的订单' : '所有已付款订单均已正常交付' }}
                      </div>
                    </div>
                  </div>
                  <el-button size="small" :type="(data.pending_manual_orders || 0) > 0 ? 'warning' : 'default'">
                    {{ (data.pending_manual_orders || 0) > 0 ? '立即处理' : '查看订单' }}
                  </el-button>
                </div>
              </div>

              <!-- 风控态势看板（去除冗长伪安全文字，呈现真实数据） -->
              <div class="dash-card risk-card">
                <div class="card-head">
                  <div class="head-title">
                    <span>近 7 天风控与安全</span>
                  </div>
                  <el-tag :type="data.risk_events.some((r) => !r.resolved) ? 'danger' : 'success'" size="small">
                    {{ data.risk_events.some((r) => !r.resolved) ? '有未解除风控' : '全域正常' }}
                  </el-tag>
                </div>

                <div class="risk-body">
                  <!-- 无风控时的极简纯净态 -->
                  <div v-if="!data.risk_events.length" class="safe-state-box">
                    <div class="safe-banner">
                      <el-icon class="safe-icon" :size="20"><CircleCheck /></el-icon>
                      <div class="safe-text">近 7 天未触发平台限制，拟人化流控与账号会话保持健康</div>
                    </div>
                    <div class="safe-tags">
                      <span class="safe-chip">拟人化随机延迟 (1.5s~3.5s)</span>
                      <span class="safe-chip">多账号会话隔离</span>
                      <span class="safe-chip">自动梯级限流冷却</span>
                    </div>
                  </div>

                  <!-- 发生风控记录时的时间线 -->
                  <div v-else class="risk-timeline-wrap">
                    <el-timeline class="compact-timeline">
                      <el-timeline-item
                        v-for="(r, i) in data.risk_events"
                        :key="r.id ?? i"
                        :timestamp="fmtTime(r.created_at)"
                        :type="r.resolved ? 'success' : r.state === 'circuit_open' ? 'danger' : 'warning'"
                        size="normal"
                      >
                        <div class="timeline-row">
                          <span class="acc-name">{{ accountName(r.account_id) }}</span>
                          <el-tag
                            :type="r.resolved ? 'success' : (accountStatusMap[r.state]?.type || 'danger')"
                            size="small"
                          >
                            {{ r.resolved ? '已恢复' : (accountStatusMap[r.state]?.label || r.state) }}
                          </el-tag>
                        </div>
                        <div class="timeline-reason">{{ r.reason || '短时访问频次过高或接口临时限流' }}</div>
                        <div v-if="!r.resolved" class="timeline-actions">
                          <el-link
                            v-if="r.punish_url"
                            :href="r.punish_url"
                            target="_blank"
                            type="danger"
                            class="action-link"
                          >
                            手动解除验证 ↗
                          </el-link>
                          <router-link
                            v-if="r.state === 'need_login'"
                            :to="{ path: '/accounts', query: { relogin: String(r.account_id) } }"
                            class="action-link text-primary"
                          >
                            重新登录此账号 ↗
                          </router-link>
                        </div>
                      </el-timeline-item>
                    </el-timeline>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- AI 与系统调度视图 -->
          <div v-show="activeTab === 'all' || activeTab === 'system'" class="dash-row two-col">
            <!-- 左侧：AI 大模型服务引擎 -->
            <div class="dash-card llm-card">
              <div class="card-head">
                <div class="head-title">
                  <span>AI 大模型服务</span>
                  <span class="status-indicator" :class="llm?.available ? 'ok' : 'err'">
                    {{ llm?.available ? '就绪' : '异常' }}
                  </span>
                </div>
                <el-button size="small" :icon="Setting" @click="router.push('/llm')">模型配置</el-button>
              </div>

              <div class="llm-body">
                <template v-if="llm">
                  <div class="metric-row">
                    <div class="metric-item">
                      <span class="label">服务提供商</span>
                      <span class="val">{{ llm.provider || '未配置' }}</span>
                    </div>
                    <div class="metric-item">
                      <span class="label">今日调用次数</span>
                      <span class="val mono">{{ llm.usage_today.calls }} 次</span>
                    </div>
                    <div class="metric-item">
                      <span class="label">今日消耗 Tokens</span>
                      <span class="val mono">{{ tokenUsed.toLocaleString() }}</span>
                    </div>
                  </div>

                  <div class="model-tiers-wrap">
                    <span class="tier-label">模型分工：</span>
                    <div class="tier-chips">
                      <div v-for="(m, tier) in llm.models" :key="tier" class="model-chip">
                        <span class="t-name">{{ tier === 'chat' ? '对话' : tier === 'vision' ? '多模视觉' : '极速意图' }}</span>
                        <span class="t-model mono">{{ m || '-' }}</span>
                      </div>
                    </div>
                  </div>

                  <div v-if="llm.usage_today.budget" class="budget-box">
                    <div class="budget-meta">
                      <span class="label">每日 Token 预算进度</span>
                      <span class="pct mono">{{ tokenPercent }}% ({{ tokenUsed.toLocaleString() }} / {{ (llm.usage_today.budget || 0).toLocaleString() }})</span>
                    </div>
                    <el-progress
                      :percentage="tokenPercent"
                      :status="tokenPercent > 90 ? 'exception' : undefined"
                      :stroke-width="5"
                      :show-text="false"
                    />
                  </div>
                </template>
                <div v-else class="muted">尚未配置 LLM 模型，可前往模型配置中绑定。</div>
              </div>
            </div>

            <!-- 右侧：后台守护与调度任务队列 -->
            <div class="dash-card system-card">
              <div class="card-head">
                <div class="head-title">
                  <span>后台守护与调度</span>
                </div>
                <el-button size="small" :icon="Tools" @click="router.push('/system')">调度设置</el-button>
              </div>

              <div class="system-body">
                <!-- 4 守护引擎状态 -->
                <div class="daemon-grid">
                  <div class="daemon-pill" :class="{ on: data.system.im_running }">
                    <span class="dot" />
                    <span class="name">IM 消息长连接</span>
                    <span class="state">{{ data.system.im_running ? '监听中' : '未启动' }}</span>
                  </div>

                  <div class="daemon-pill on" @click="router.push('/radar/smart')">
                    <span class="dot" />
                    <span class="name">选品监控定时</span>
                    <span class="state">{{ data.monitor_tasks ?? 0 }} 个生效</span>
                  </div>

                  <div class="daemon-pill" :class="{ on: autoDeliveryOn }" @click="router.push('/orders/cards')">
                    <span class="dot" />
                    <span class="name">自动发货守护</span>
                    <span class="state">{{ autoDeliveryOn ? '全天候待命' : '未开启' }}</span>
                  </div>

                  <div class="daemon-pill" :class="{ on: autoReplyOn }" @click="router.push('/messages/rules')">
                    <span class="dot" />
                    <span class="name">智能回复引擎</span>
                    <span class="state">{{ autoReplyOn ? '实时应答就绪' : '未开启' }}</span>
                  </div>
                </div>

                <!-- 定时调度任务列表 -->
                <div v-if="data.system.jobs.length" class="jobs-list">
                  <div class="jobs-head">
                    <el-icon><Timer /></el-icon>
                    <span>巡检任务队列 ({{ data.system.jobs.length }})</span>
                  </div>
                  <div class="jobs-items">
                    <div v-for="j in data.system.jobs" :key="j.id" class="job-row">
                      <div class="j-left">
                        <span class="j-tag" :class="getJobMeta(j.id).tagType">{{ getJobMeta(j.id).category }}</span>
                        <span class="j-name">{{ getJobMeta(j.id).title }}</span>
                      </div>
                      <span class="j-time mono">{{ fmtJobNextRun(j.next_run) }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </template>

    <el-empty v-else-if="!loading && !loadError" description="暂无工作台数据">
      <el-button @click="load">重新读取</el-button>
    </el-empty>
  </div>
</template>

<style scoped>
.dashboard-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  animation: fadeIn 0.2s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(3px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 顶部状态栏 */
.dash-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.page-title-text {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.015em;
  color: var(--xh-text);
}

.live-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: var(--xh-radius-pill);
  font-size: 12px;
  font-weight: 500;
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
  border: 1px solid var(--xh-primary-border);
}

.live-status-pill.off {
  background: #f1f5f9;
  color: var(--xh-muted);
  border-color: var(--xh-border);
}

.pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.info-help-icon {
  color: var(--xh-muted);
  cursor: pointer;
  display: inline-flex;
  font-size: 14px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.alert-capsule-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: var(--xh-radius-pill);
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.15s ease;
}

.alert-capsule-btn.warning {
  background: #fffbeb;
  color: var(--xh-warning-text);
  border-color: #fde68a;
}
.alert-capsule-btn.warning:hover {
  background: #fef3c7;
}

.alert-capsule-btn.danger {
  background: #fff1f2;
  color: var(--xh-danger);
  border-color: #fecdd3;
}
.alert-capsule-btn.danger:hover {
  background: #fee2e2;
}

.sync-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.last-sync-time {
  font-size: 12px;
  color: var(--xh-muted);
  font-variant-numeric: tabular-nums;
}

/* Stripe 风格 Executive KPI 卡片流 */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px;
}

.kpi-card {
  background: #ffffff;
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: 14px 16px;
  cursor: pointer;
  transition: all 0.15s ease;
  box-shadow: var(--xh-shadow-1);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.kpi-card:hover {
  border-color: var(--xh-border-strong);
  box-shadow: var(--xh-shadow-2);
  transform: translateY(-1px);
}

.kpi-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.kpi-label {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--xh-text-2);
}

.kpi-icon {
  font-size: 15px;
  color: var(--xh-muted);
}

.kpi-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--xh-text);
  letter-spacing: -0.02em;
  line-height: 1.15;
}

.kpi-footer {
  font-size: 12px;
  color: var(--xh-muted);
}

/* 分段导航 */
.dash-seg-control {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 4px 0 12px;
  border-bottom: 1px solid var(--xh-border);
  padding-bottom: 8px;
}

.seg-pills {
  display: inline-flex;
  background: var(--xh-fill);
  padding: 3px;
  border-radius: 8px;
  gap: 3px;
}

.seg-pill {
  border: none;
  background: transparent;
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--xh-text-2);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transition: all 0.15s ease;
}

.seg-pill.active {
  background: #ffffff;
  color: var(--xh-text);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.pill-badge {
  background: var(--xh-fill-strong);
  font-size: 11px;
  padding: 0 5px;
  border-radius: 10px;
}

.im-status-chip {
  font-size: 12.5px;
  color: var(--xh-text-2);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.chip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #cbd5e1;
}

.chip-dot.on {
  background: var(--xh-primary);
}

/* 内容面板布局 */
.dash-panes {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.dash-row.two-col {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
  gap: 14px;
}

@media (max-width: 992px) {
  .dash-row.two-col {
    grid-template-columns: 1fr;
  }
}

/* 通用仪表盘卡片 */
.dash-card {
  background: #ffffff;
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  box-shadow: var(--xh-shadow-1);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--xh-border);
}

.head-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--xh-text);
}

.count-tag {
  background: var(--xh-fill);
  font-size: 11px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 10px;
  color: var(--xh-muted);
}

.status-indicator {
  font-size: 12px;
  font-weight: 500;
  padding: 1px 7px;
  border-radius: 4px;
}

.status-indicator.ok {
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
}

.status-indicator.err {
  background: #fff1f2;
  color: var(--xh-danger);
}

/* 账号单元格 */
.account-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.acc-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  flex-shrink: 0;
}

.acc-avatar img {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
}

.dot-indicator {
  position: absolute;
  bottom: -1px;
  right: -1px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  border: 1.5px solid #ffffff;
}

.dot-indicator.online { background: var(--xh-primary); }
.dot-indicator.offline { background: #cbd5e1; }

.acc-info .nick {
  font-size: 13px;
  font-weight: 500;
  color: var(--xh-text);
  max-width: 110px;
}

.acc-info .unb {
  font-size: 11px;
  color: var(--xh-muted);
}

.health-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.health-num {
  font-size: 12px;
  font-weight: 600;
  width: 32px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

/* 自动化效能统计条 */
.telemetry-bar {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  border-top: 1px solid var(--xh-border);
  background: var(--xh-fill);
}

.telemetry-item {
  padding: 10px 14px;
  cursor: pointer;
  transition: background 0.15s ease;
  border-right: 1px solid var(--xh-border);
}

.telemetry-item:last-child {
  border-right: none;
}

.telemetry-item:hover {
  background: #eef2f6;
}

.telemetry-item .t-label {
  font-size: 11.5px;
  color: var(--xh-muted);
  display: block;
}

.telemetry-item .t-data {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-top: 2px;
}

.telemetry-item .t-val {
  font-size: 16px;
  font-weight: 700;
  color: var(--xh-text);
  font-variant-numeric: tabular-nums;
}

.telemetry-item .t-sub {
  font-size: 11.5px;
  color: var(--xh-muted);
}

/* 待办中心 */
.right-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.pending-card {
  padding: 12px 14px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.pending-card.alert {
  border-color: #fde68a;
  background: #fffdf5;
}

.pending-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.pending-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.status-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.status-icon.warning {
  background: #fef3c7;
  color: var(--xh-warning-text);
}

.status-icon.ok {
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
}

.p-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--xh-text);
}

.p-desc {
  font-size: 12px;
  color: var(--xh-muted);
  margin-top: 2px;
}

/* 风控态势 */
.risk-body {
  padding: 14px 16px;
}

.safe-state-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.safe-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--xh-text);
  font-size: 13px;
  font-weight: 500;
}

.safe-icon {
  color: var(--xh-primary);
}

.safe-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.safe-chip {
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 12px;
  color: var(--xh-text-2);
}

.compact-timeline {
  padding-left: 4px;
}

.timeline-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 3px;
}

.timeline-reason {
  font-size: 12px;
  color: var(--xh-muted);
}

.timeline-actions {
  margin-top: 4px;
  display: flex;
  gap: 10px;
}

.action-link {
  font-size: 12px;
}

/* AI 与系统服务 */
.llm-body,
.system-body {
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.metric-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.metric-item .label {
  font-size: 12px;
  color: var(--xh-muted);
  display: block;
}

.metric-item .val {
  font-size: 15px;
  font-weight: 600;
  color: var(--xh-text);
  margin-top: 2px;
  display: block;
}

.model-tiers-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
}

.tier-label {
  color: var(--xh-muted);
}

.tier-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.model-chip {
  background: var(--xh-fill);
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  display: inline-flex;
  gap: 6px;
}

.model-chip .t-name {
  color: var(--xh-muted);
}

.model-chip .t-model {
  color: var(--xh-text);
  font-weight: 500;
}

.budget-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.budget-meta {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--xh-muted);
}

.daemon-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.daemon-pill {
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  border-radius: 6px;
  padding: 8px 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.daemon-pill:hover {
  border-color: var(--xh-border-strong);
}

.daemon-pill .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #cbd5e1;
  margin-right: 6px;
}

.daemon-pill.on .dot {
  background: var(--xh-primary);
}

.daemon-pill .state {
  font-size: 12px;
  color: var(--xh-muted);
}

.jobs-list {
  border-top: 1px solid var(--xh-border);
  padding-top: 10px;
}

.jobs-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--xh-text-2);
  margin-bottom: 8px;
}

.jobs-items {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 140px;
  overflow-y: auto;
}

.job-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  padding: 4px 6px;
  border-radius: 4px;
  background: var(--xh-fill);
}

.j-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.j-tag {
  font-size: 10.5px;
  padding: 1px 4px;
  border-radius: 3px;
  background: #e2e8f0;
  color: var(--xh-text-2);
}

.j-name {
  color: var(--xh-text);
  font-weight: 500;
}

.j-time {
  color: var(--xh-muted);
}
</style>
