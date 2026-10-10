<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRealtimeStore } from '@/stores/realtime'
import { useRouter } from 'vue-router'
import {
  Aim,
  Box,
  ChatDotRound,
  CircleCheck,
  Cpu,
  DataLine,
  InfoFilled,
  Lightning,
  Money,
  Plus,
  Promotion,
  Reading,
  Refresh,
  Right,
  Search,
  Setting,
  Timer,
  Tools,
  TrendCharts,
  User,
  UserFilled,
  Warning,
} from '@element-plus/icons-vue'
import { getDashboard, type Dashboard, type DashboardAccount } from '@/api/dashboard'
import { updateAccount } from '@/api/account'
import { ElMessage } from 'element-plus'
import StatusTag from '@/components/StatusTag.vue'
import { NEEDS_ACTION_STATUSES, accountStatusMap, fmtMoney, fmtTime } from '@/utils/format'

const router = useRouter()
const realtime = useRealtimeStore()
const data = ref<Dashboard | null>(null)
const loading = ref(false)
const quickKeyword = ref('')
const activeTab = ref<'accounts' | 'search' | 'system'>('accounts')
let timer: number | undefined

function goToSearch() {
  const kw = quickKeyword.value.trim()
  if (!kw) {
    router.push('/radar/search')
    return
  }
  router.push({ path: '/radar/search', query: { q: kw } })
}

function searchByKeyword(kw: string) {
  router.push({ path: '/radar/search', query: { q: kw } })
}

async function load() {
  loading.value = true
  try {
    data.value = await getDashboard()
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
  const orders = t ? Object.values(t.orders).reduce((a, b) => a + b, 0) : 0
  const radar = t ? (t.radar.recommend || 0) + (t.radar.conditional || 0) : 0
  return [
    {
      label: '今日买家消息',
      value: t?.messages_in ?? 0,
      hint: `人工已回 ${t?.messages_manual ?? 0} 条`,
      icon: ChatDotRound,
      color: '#3b82f6',
      bg: 'rgba(59, 130, 246, 0.1)',
      path: '/messages/inbox',
    },
    {
      label: '自动智能接待',
      value: t?.messages_auto ?? 0,
      hint: '关键词 + AI 接待',
      icon: Lightning,
      color: '#8b5cf6',
      bg: 'rgba(139, 92, 246, 0.1)',
      path: '/messages/rules',
    },
    {
      label: '自动发货卡密',
      value: t?.deliveries ?? 0,
      hint: '已发出的发货卡密',
      icon: Promotion,
      color: '#10b981',
      bg: 'rgba(16, 185, 129, 0.1)',
      path: '/orders/cards',
    },
    {
      label: '今日订单成交',
      value: orders,
      hint: '含待付款全量订单',
      icon: Box,
      color: '#f97316',
      bg: 'rgba(249, 115, 22, 0.1)',
      path: '/orders/list',
    },
    {
      label: '今日成交 GMV',
      value: fmtMoney(t?.gmv ?? 0),
      hint: '成交金额 (扣除退款)',
      icon: Money,
      color: '#eab308',
      bg: 'rgba(234, 179, 8, 0.1)',
      path: '/orders/list',
    },
    {
      label: '选品雷达推荐',
      value: radar,
      hint: `捡漏 ${t?.radar.recommend || 0} · 需核 ${t?.radar.conditional || 0}`,
      icon: DataLine,
      color: '#06b6d4',
      bg: 'rgba(6, 182, 212, 0.1)',
      path: '/radar/smart',
    },
  ]
})

const llm = computed(() => data.value?.system.llm)
const tokenUsed = computed(() => (llm.value ? llm.value.usage_today.input_tokens + llm.value.usage_today.output_tokens : 0))
const tokenPercent = computed(() => {
  const b = llm.value?.usage_today.budget || 0
  return b > 0 ? Math.min(100, Math.round((tokenUsed.value / b) * 100)) : 0
})

const autoReplyOn = computed(() => !!data.value?.accounts.some((a) => a.auto_reply))
const autoDeliveryOn = computed(() => !!data.value?.accounts.some((a) => a.auto_delivery))
const restrictedCount = computed(
  () => data.value?.accounts.filter((a) => ['cooldown', 'circuit_open', 'need_login'].includes(a.status)).length || 0,
)
const imOnlineCount = computed(() => data.value?.accounts.filter((a) => a.im_connected).length || 0)
const autoManagedCount = computed(
  () => data.value?.accounts.filter((a) => a.auto_reply || a.auto_delivery).length || 0,
)

function accountName(id: number | null) {
  if (id === null) return '系统'
  return data.value?.accounts.find((a) => a.id === id)?.nickname || `#${id}`
}

function healthColor(h: number) {
  if (h >= 80) return '#10b981'
  if (h >= 50) return '#f59e0b'
  return '#ef4444'
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
  return jobMetaMap[id] || {
    title: id,
    desc: '系统常规后台调度任务',
    category: '调度',
    tagType: 'info',
  }
}

function fmtJobNextRun(v: string | null | undefined): string {
  if (!v) return '就绪中'
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return v
  const p = (n: number) => String(n).padStart(2, '0')
  const now = new Date()
  const isToday = d.toDateString() === now.toDateString()
  const timeStr = `${p(d.getHours())}:${p(d.getMinutes())}`
  return isToday ? `今日 ${timeStr}` : `${p(d.getMonth() + 1)}-${p(d.getDate())} ${timeStr}`
}
</script>

<template>
  <div v-loading="loading && !data" class="page dashboard-page">
    <!-- 顶部状态栏 -->
    <header class="dash-header">
      <div class="header-left">
        <h2 class="page-title-text">
          总览工作台
          <span class="live-pill">
            <span class="live-pulse" />
            实时监控中
          </span>
        </h2>
      </div>

      <div class="header-right">
        <!-- 待办订单报警胶囊 (高亮突出) -->
        <div
          v-if="(data?.pending_manual_orders || 0) > 0"
          class="pending-alarm-pill active"
          @click="router.push({ path: '/orders/list', query: { status: NEEDS_ACTION_STATUSES } })"
        >
          <el-icon class="alarm-icon"><Warning /></el-icon>
          <span>{{ data?.pending_manual_orders }} 笔订单待人工处理</span>
          <el-icon class="arrow-right"><Right /></el-icon>
        </div>
        <div
          v-else
          class="pending-alarm-pill calm"
          @click="router.push('/orders/list')"
        >
          <el-icon class="check-icon"><CircleCheck /></el-icon>
          <span>订单全部处理完毕</span>
        </div>

        <el-button :icon="Refresh" :loading="loading" size="small" class="refresh-btn" round @click="load">
          刷新数据
        </el-button>
      </div>
    </header>

    <!-- 核心指标卡片矩阵 (紧凑单行 6 列) -->
    <section class="kpi-section">
      <div
        v-for="k in kpis"
        :key="k.label"
        class="kpi-card"
        :style="{ borderTopColor: k.color }"
        @click="router.push(k.path)"
      >
        <div class="kpi-header">
          <span class="kpi-label">{{ k.label }}</span>
          <div class="kpi-icon-bubble" :style="{ color: k.color, backgroundColor: k.bg }">
            <el-icon :size="15"><component :is="k.icon" /></el-icon>
          </div>
        </div>
        <div class="kpi-value" :style="{ color: k.value === '¥0' || k.value === 0 ? '#1e293b' : k.color }">
          {{ k.value }}
        </div>
        <div class="kpi-footer">
          <span class="kpi-hint">{{ k.hint }}</span>
          <el-icon class="kpi-arrow"><Right /></el-icon>
        </div>
      </div>
    </section>

    <!-- 主工作区：满高弹性容器 (Flex-1 Fill Remaining Viewport) -->
    <main class="dash-main-container">
      <!-- 现代化 Segmented Capsule 分段药丸导航栏（告别老旧 tabs 边框与变形角标） -->
      <nav class="dash-segmented-bar">
        <div class="seg-nav-list" role="tablist">
          <button
            type="button"
            class="seg-nav-item"
            :class="{ 'is-active': activeTab === 'accounts' }"
            role="tab"
            :aria-selected="activeTab === 'accounts'"
            @click="activeTab = 'accounts'"
          >
            <el-icon class="seg-icon"><UserFilled /></el-icon>
            <span class="seg-label">闲鱼账号与风控</span>
            <span v-if="data?.accounts.length" class="seg-counter-badge">{{ data.accounts.length }}</span>
          </button>

          <button
            type="button"
            class="seg-nav-item"
            :class="{ 'is-active': activeTab === 'search' }"
            role="tab"
            :aria-selected="activeTab === 'search'"
            @click="activeTab = 'search'"
          >
            <el-icon class="seg-icon"><Search /></el-icon>
            <span class="seg-label">闲鱼实时找货</span>
            <span class="seg-tag-pill">免建监控</span>
          </button>

          <button
            type="button"
            class="seg-nav-item"
            :class="{ 'is-active': activeTab === 'system' }"
            role="tab"
            :aria-selected="activeTab === 'system'"
            @click="activeTab = 'system'"
          >
            <el-icon class="seg-icon"><Cpu /></el-icon>
            <span class="seg-label">AI 引擎与后台服务</span>
            <span class="seg-status-dot" :class="llm?.available ? 'online' : 'offline'" />
          </button>
        </div>

        <div class="seg-nav-meta">
          <div class="im-health-pill">
            <span class="pulse-indicator" :class="imOnlineCount > 0 ? 'online' : 'idle'" />
            <span class="meta-label">IM 实时长连接:</span>
            <span class="meta-val mono">{{ imOnlineCount }} / {{ data?.accounts.length || 0 }}</span>
            <span class="meta-sub">在线</span>
          </div>
        </div>
      </nav>

      <!-- 标签页视口容器 -->
      <div class="dash-tabs-viewport">
        <!-- 页面 1: 闲鱼账号与风控防护 -->
        <div v-show="activeTab === 'accounts'" class="tab-pane-view">
          <div class="tab-grid-layout two-cols">
            <!-- 左侧：账号管理与自动化运行大盘 -->
            <div class="panel-box accounts-panel">
              <div class="panel-header">
                <div class="title-with-subtitle">
                  <span class="panel-title">已接入闲鱼账号</span>
                </div>
                <div class="panel-action-group">
                  <button type="button" class="mini-capsule-btn ghost" @click="router.push('/accounts')">
                    <el-icon><Plus /></el-icon>
                    <span>接入账号</span>
                  </button>
                  <button type="button" class="mini-capsule-btn primary" @click="router.push('/accounts')">
                    <el-icon><User /></el-icon>
                    <span>账号管理中心</span>
                    <el-icon class="arrow-ico"><Right /></el-icon>
                  </button>
                </div>
              </div>

              <!-- 账号列表：自适应紧凑高度，多账号时支持内滚 -->
              <div class="account-table-container">
                <el-table
                  :data="data?.accounts || []"
                  size="small"
                  empty-text="还没有添加闲鱼账号，请前往账号管理添加"
                  class="modern-account-table"
                  max-height="160"
                >
                  <el-table-column label="账号昵称" min-width="160">
                    <template #default="{ row }">
                      <div class="account-profile">
                        <div class="avatar-bubble">
                          <span>{{ (row.remark || row.nickname || '闲')[0] }}</span>
                          <span class="status-dot-pulse" :class="row.im_connected ? 'online' : 'offline'" />
                        </div>
                        <div class="account-texts">
                          <div class="acc-nick">{{ row.remark || row.nickname || '闲鱼卖家' }}</div>
                          <div class="acc-id mono">{{ row.nickname }}</div>
                        </div>
                      </div>
                    </template>
                  </el-table-column>

                  <el-table-column label="运行状态" width="105">
                    <template #default="{ row }">
                      <StatusTag :value="row.status" :map="accountStatusMap" />
                    </template>
                  </el-table-column>

                  <el-table-column label="健康评分" min-width="130">
                    <template #default="{ row }">
                      <div class="health-cell">
                        <el-progress
                          :percentage="row.health"
                          :color="healthColor(row.health)"
                          :stroke-width="6"
                          :show-text="false"
                          class="health-bar"
                        />
                        <span class="health-text" :style="{ color: healthColor(row.health) }">{{ row.health }}%</span>
                      </div>
                    </template>
                  </el-table-column>

                  <el-table-column label="消息长连接" width="100">
                    <template #default="{ row }">
                      <div class="connection-tag" :class="row.im_connected ? 'is-connected' : 'is-disconnected'">
                        <span class="con-dot" />
                        <span>{{ row.im_connected ? '在线' : '离线' }}</span>
                      </div>
                    </template>
                  </el-table-column>

                  <el-table-column label="自动回复" width="90">
                    <template #default="{ row }">
                      <el-switch
                        :model-value="row.auto_reply"
                        :loading="busy[`reply-${row.id}`]"
                        active-text="开"
                        inactive-text="关"
                        inline-prompt
                        size="small"
                        @change="(v: string | number | boolean) => toggleAccountReply(row as DashboardAccount, !!v)"
                      />
                    </template>
                  </el-table-column>

                  <el-table-column label="自动发货" width="90">
                    <template #default="{ row }">
                      <el-switch
                        :model-value="row.auto_delivery"
                        :loading="busy[`deliv-${row.id}`]"
                        active-text="开"
                        inactive-text="关"
                        inline-prompt
                        size="small"
                        @change="(v: string | number | boolean) => toggleAccountDelivery(row as DashboardAccount, !!v)"
                      />
                    </template>
                  </el-table-column>
                </el-table>
              </div>

              <!-- 下半部分：今日自动化运行与效能指标（充满剩余高度，丰富实用） -->
              <div class="automation-telemetry-section">
                <div class="telemetry-head">
                  <span class="telemetry-title">今日自动化</span>
                </div>
                <div class="telemetry-grid">
                  <div class="telemetry-card" @click="router.push('/messages/rules')">
                    <div class="tc-top">
                      <span class="tc-label">自动回复</span>
                      <span class="tc-status" :class="autoReplyOn ? 'online' : 'off'">{{ autoReplyOn ? '已开启' : '未开启' }}</span>
                    </div>
                    <div class="tc-val">{{ data?.today.messages_auto || 0 }} <span class="tc-unit">条</span></div>
                    <div class="tc-desc">
                      今日收到 {{ data?.today.messages_in || 0 }} 条消息 · 人工已回 {{ data?.today.messages_manual || 0 }} 条
                    </div>
                  </div>

                  <div class="telemetry-card" @click="router.push('/orders/cards')">
                    <div class="tc-top">
                      <span class="tc-label">自动发货</span>
                      <span class="tc-status" :class="autoDeliveryOn ? 'online' : 'off'">{{ autoDeliveryOn ? '已开启' : '未开启' }}</span>
                    </div>
                    <div class="tc-val">{{ data?.today.deliveries || 0 }} <span class="tc-unit">笔</span></div>
                    <div class="tc-desc">
                      待人工处理 {{ data?.pending_manual_orders || 0 }} 笔
                    </div>
                  </div>

                  <div class="telemetry-card" @click="router.push('/accounts')">
                    <div class="tc-top">
                      <span class="tc-label">账号风控</span>
                      <span class="tc-status" :class="restrictedCount ? 'warn' : 'online'">{{ restrictedCount ? '有账号受限' : '全部正常' }}</span>
                    </div>
                    <div class="tc-val">{{ restrictedCount }} <span class="tc-unit">个账号受限</span></div>
                    <div class="tc-desc">
                      今日风控拦截 {{ data?.risk_events.length || 0 }} 条
                    </div>
                  </div>
                </div>
              </div>

              <!-- 卡片底部状态汇总条 -->
              <div class="panel-footer-bar">
                <span class="footer-tip">
                  共接入 {{ data?.accounts.length || 0 }} 个账号 · {{ imOnlineCount }} 个消息在线 · {{ autoManagedCount }} 个开启自动化
                </span>
                <el-button link type="primary" size="small" :icon="Setting" @click="router.push('/accounts')">
                  配置接入
                </el-button>
              </div>
            </div>

            <!-- 右侧：待办中心 + 风控安全态势 (上下双卡片垂直排列，撑满 100% 高度) -->
            <div class="right-stack-col">
              <!-- 上部：待办订单与履约中心 -->
              <div class="panel-box orders-pending-panel" :class="{ 'has-alarm': (data?.pending_manual_orders || 0) > 0 }">
                <div class="pending-panel-inner" @click="router.push('/orders/list')">
                  <div class="pending-left">
                    <div class="pending-icon-wrap" :class="(data?.pending_manual_orders || 0) > 0 ? 'alarm' : 'calm'">
                      <el-icon :size="24"><component :is="(data?.pending_manual_orders || 0) > 0 ? Warning : CircleCheck" /></el-icon>
                    </div>
                    <div>
                      <div class="pending-status-title">
                        {{ (data?.pending_manual_orders || 0) > 0 ? `${data?.pending_manual_orders} 笔订单待人工处理` : '全部订单处理完毕' }}
                      </div>
                      <div class="pending-status-sub">
                        {{ (data?.pending_manual_orders || 0) > 0 ? '买家付款或缺货待核验，请及时处理' : '履约通道畅通' }}
                      </div>
                    </div>
                  </div>
                  <div class="pending-action-btn">
                    <span class="btn-text">{{ (data?.pending_manual_orders || 0) > 0 ? '去处理' : '订单中心' }}</span>
                    <el-icon><Right /></el-icon>
                  </div>
                </div>
              </div>

              <!-- 下部：近 7 天智能安全防护 (充实专业感与风控座舱) -->
              <div class="panel-box risk-panel">
                <div class="panel-header">
                  <div class="title-with-subtitle">
                    <span class="panel-title">风控记录</span>
                  </div>
                  <div class="panel-actions">
                    <el-tag :type="data?.risk_events.some((r) => !r.resolved) ? 'danger' : 'success'" size="small">
                      {{ data?.risk_events.some((r) => !r.resolved) ? '有未解除的限制' : '无未解除的限制' }}
                    </el-tag>
                  </div>
                </div>

                <div class="panel-body">
                  <!-- 安全平稳运行态势展示 (告别死白与巨大空洞) -->
                  <div v-if="!data?.risk_events.length" class="shield-active-state">
                    <div class="shield-banner">
                      <div class="shield-icon-circle">
                        <el-icon :size="20"><CircleCheck /></el-icon>
                      </div>
                      <div class="shield-banner-info">
                        <span class="shield-banner-title">全域安全防护运行正常</span>
                        <span class="shield-banner-sub">近 7 天未触发平台限制，拟人化安全机制全天候值守</span>
                      </div>
                    </div>

                    <div class="shield-guard-grid">
                      <div class="guard-metric-card">
                        <div class="gm-label">拟人化访问控频</div>
                        <div class="gm-val mono">1.5s ~ 3.5s</div>
                        <div class="gm-tag ok">动态随机延迟</div>
                      </div>
                      <div class="guard-metric-card">
                        <div class="gm-label">平台限流自愈</div>
                        <div class="gm-val mono">自动梯级冷却</div>
                        <div class="gm-tag info">阻断重试保护</div>
                      </div>
                      <div class="guard-metric-card">
                        <div class="gm-label">多账号隔离</div>
                        <div class="gm-val mono">{{ data?.accounts.length || 0 }} 个独立环境</div>
                        <div class="gm-tag ok">Session 指纹沙箱</div>
                      </div>
                    </div>

                    <div class="shield-footer-tip">
                      <span><el-icon class="tip-icon"><InfoFilled /></el-icon> 实时监听闲鱼滑块与登录状态，如遇风控将在此自动生成人工解除链接并即时通知。</span>
                    </div>
                  </div>

                  <!-- 发生风控记录时的时间线 -->
                  <div v-else class="risk-timeline-container">
                    <el-timeline class="compact-timeline">
                      <el-timeline-item
                        v-for="(r, i) in data.risk_events"
                        :key="r.id ?? i"
                        :timestamp="fmtTime(r.created_at)"
                        :type="r.resolved ? 'success' : r.state === 'circuit_open' ? 'danger' : 'warning'"
                        size="normal"
                      >
                        <div class="timeline-row">
                          <span class="acc-badge">{{ accountName(r.account_id) }}</span>
                          <StatusTag :value="r.state" :map="accountStatusMap" />
                          <el-tag v-if="r.resolved" size="small" type="success" effect="plain" class="ml-s">已自愈解除</el-tag>
                        </div>
                        <div class="timeline-reason">{{ r.reason || '短时访问频次过高或接口临时限流' }}</div>
                        <el-link
                          v-if="r.punish_url && !r.resolved"
                          :href="r.punish_url"
                          target="_blank"
                          type="danger"
                          class="small mt-xs inline-block"
                        >
                          打开闲鱼验证页面手动解除 &gt;
                        </el-link>
                      </el-timeline-item>
                    </el-timeline>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 页面 2: 闲鱼实时找货引擎 -->
        <div v-show="activeTab === 'search'" class="tab-pane-view">

          <div class="tab-search-wrapper">
            <!-- 找货 Hero 卡片 -->
            <div class="search-hero-card">
              <div class="hero-top-row">
                <div class="hero-brand">
                  <div class="search-badge-icon">
                    <el-icon :size="20"><Search /></el-icon>
                  </div>
                  <div>
                    <h3 class="hero-title">
                      闲鱼全量一手货源实时探索
                      <el-tag size="small" type="success" effect="plain" class="hero-tag">免建监控 · 即搜即看</el-tag>
                    </h3>
                  </div>
                </div>

                <div class="hero-input-box">
                  <el-input
                    v-model="quickKeyword"
                    placeholder="输入商品型号（如 iPhone 15、MacBook M1、Switch OLED），回车立即搜索"
                    size="large"
                    clearable
                    class="custom-hero-input"
                    @keyup.enter="goToSearch"
                  >
                    <template #append>
                      <el-button type="primary" :icon="Search" class="hero-submit-btn" @click="goToSearch">
                        立即找货
                      </el-button>
                    </template>
                  </el-input>
                </div>
              </div>

              <!-- 分类热门关键词 -->
              <div class="hero-hot-section">
                <span class="hot-label">热门搜索：</span>
                <div class="hot-chips-list">
                  <span
                    v-for="k in ['MacBook M1', 'iPhone 15', 'Switch OLED', 'PS5', '显卡 RTX', 'iPad Air', 'AirPods Pro', '机械键盘']"
                    :key="k"
                    class="hot-chip"
                    @click="searchByKeyword(k)"
                  >
                    {{ k }}
                  </span>
                </div>
                <el-button link type="primary" size="small" class="jump-radar-btn" @click="router.push('/radar/search')">
                  进入完整选品雷达工作台 &gt;
                </el-button>
              </div>
            </div>

            <!-- 3 大核心业务入口卡片 (紧凑精致，带明确操作指引) -->
            <div class="radar-workflow-grid">
              <div class="workflow-card" @click="router.push('/radar/search')">
                <div class="wf-icon-wrap icon-blue">
                  <el-icon :size="20"><Search /></el-icon>
                </div>
                <div class="wf-content">
                  <div class="wf-name">实时搜货</div>
                  <div class="wf-desc">秒级同步闲鱼一手货源、底价与卖家信誉</div>
                </div>
                <div class="wf-action-pill">
                  <span>立即搜货</span>
                  <el-icon><Right /></el-icon>
                </div>
              </div>

              <div class="workflow-card" @click="router.push('/radar/smart')">
                <div class="wf-icon-wrap icon-purple">
                  <el-icon :size="20"><Aim /></el-icon>
                </div>
                <div class="wf-content">
                  <div class="wf-name">智能搜索 · 盯价</div>
                  <div class="wf-desc">定时自动巡检好货并 AI 深度分析，到价即提醒</div>
                </div>
                <div class="wf-action-pill">
                  <span>管理任务</span>
                  <el-icon><Right /></el-icon>
                </div>
              </div>

              <div class="workflow-card" @click="router.push('/radar/smart')">
                <div class="wf-icon-wrap icon-emerald">
                  <el-icon :size="20"><Promotion /></el-icon>
                </div>
                <div class="wf-content">
                  <div class="wf-name">一键转手发品</div>
                  <div class="wf-desc">从搜索结果中捕捉套利差价，带加价率生成文案</div>
                </div>
                <div class="wf-action-pill">
                  <span>去挑选</span>
                  <el-icon><Right /></el-icon>
                </div>
              </div>
            </div>

            <!-- 下半部分：热门类目探索矩阵与捡漏技巧 (充满视口，丰富实用) -->
            <div class="radar-discover-board">
              <div class="discover-col category-col">
                <div class="discover-head">
                  <span class="d-title"><el-icon><TrendCharts /></el-icon> 热门货源分类探索</span>
                  <span class="d-sub">点击关键词直达全网最新挂牌底价</span>
                </div>
                <div class="category-matrix">
                  <div class="cat-group">
                    <span class="cat-group-name">数码轻奢：</span>
                    <div class="cat-chips">
                      <span v-for="it in ['MacBook Air M1', 'iPhone 15 Pro', 'iPad Air 5', 'AirPods Pro 2']" :key="it" class="d-chip" @click="searchByKeyword(it)">{{ it }}</span>
                    </div>
                  </div>
                  <div class="cat-group">
                    <span class="cat-group-name">游戏电竞：</span>
                    <div class="cat-chips">
                      <span v-for="it in ['Switch OLED', 'PS5 光驱版', 'Steam Deck', 'RTX 4070']" :key="it" class="d-chip" @click="searchByKeyword(it)">{{ it }}</span>
                    </div>
                  </div>
                  <div class="cat-group">
                    <span class="cat-group-name">外设潮物：</span>
                    <div class="cat-chips">
                      <span v-for="it in ['机械键盘 客制化', '索尼微单', '佳能 G7X', '大疆无人机']" :key="it" class="d-chip" @click="searchByKeyword(it)">{{ it }}</span>
                    </div>
                  </div>
                </div>
              </div>

              <div class="discover-col tips-col">
                <div class="discover-head">
                  <span class="d-title"><el-icon><Reading /></el-icon> 闲鱼选品捡漏指南</span>
                  <span class="d-sub">提升选品成功率与防踩坑小贴士</span>
                </div>
                <div class="tips-list">
                  <div class="tip-item">
                    <span class="tip-dot" />
                    <div class="tip-content">
                      <span class="tip-strong">善用「仅看个人闲置」</span>：过滤 90% 批量加价铺货与引流号，直达一手卖家原装自用。
                    </div>
                  </div>
                  <div class="tip-item">
                    <span class="tip-dot" />
                    <div class="tip-content">
                      <span class="tip-strong">设置合理价格区间</span>：过滤超低价钓鱼与配件引流品，例如 M1 笔记本锁定在 2500~3800 元。
                    </div>
                  </div>
                  <div class="tip-item">
                    <span class="tip-dot" />
                    <div class="tip-content">
                      <span class="tip-strong">结合「价格监控」</span>：遇到心仪商品先加监控盯价，卖家多次降价时系统秒级提醒，把握最佳入手时机。
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 页面 3: AI 引擎与系统底座服务 -->
        <div v-show="activeTab === 'system'" class="tab-pane-view">
          <div class="tab-grid-layout two-cols">
            <!-- 左侧：AI 大模型算力与分工 -->
            <div class="panel-box llm-panel">
              <div class="panel-header">
                <div class="title-with-subtitle">
                  <div class="title-row-compact">
                    <span class="panel-title">AI 大模型服务引擎</span>
                    <span v-if="llm" class="status-indicator-tag" :class="llm.available ? 'success' : 'danger'">
                      <span :class="llm.available ? 'pulse-dot-green' : 'pulse-dot-red'" />
                      {{ llm.available ? '引擎正常' : '连接异常' }}
                    </span>
                  </div>
                </div>
                <div class="panel-action-group">
                  <button type="button" class="mini-capsule-btn primary" @click="router.push('/llm')">
                    <el-icon><Setting /></el-icon>
                    <span>模型配置</span>
                    <el-icon class="arrow-ico"><Right /></el-icon>
                  </button>
                </div>
              </div>

              <div class="panel-body">
                <template v-if="llm">
                  <div class="llm-details-grid">
                    <div class="metric-card">
                      <span class="m-label">当前服务提供方</span>
                      <span class="m-val">{{ llm.provider || '未配置' }}</span>
                    </div>
                    <div class="metric-card">
                      <span class="m-label">配置来源方式</span>
                      <el-tag v-if="llm.source === 'env'" size="small" type="warning" effect="plain">环境变量注入</el-tag>
                      <span v-else class="m-val">{{ llm.source || '-' }}</span>
                    </div>
                    <div class="metric-card">
                      <span class="m-label">今日调用次数</span>
                      <span class="m-val highlight">{{ llm.usage_today.calls }} 次</span>
                    </div>
                    <div class="metric-card">
                      <span class="m-label">今日 Token 消耗量</span>
                      <span class="m-val highlight">{{ tokenUsed.toLocaleString() }}</span>
                    </div>
                  </div>

                  <div class="tier-models-box">
                    <div class="tier-title">模型三层分工调度：</div>
                    <div class="tier-row">
                      <div v-for="(m, tier) in llm.models" :key="tier" class="tier-chip">
                        <span class="tier-name">{{ tier === 'chat' ? '对话模型' : tier === 'vision' ? '视觉模型' : '快速模型' }}</span>
                        <span class="tier-val mono">{{ m || '-' }}</span>
                      </div>
                    </div>
                  </div>

                  <div v-if="llm.usage_today.budget" class="budget-progress-box">
                    <div class="budget-header">
                      <span class="small-muted">每日 Token 消耗安全预算进度</span>
                      <span class="small-bold mono">{{ tokenPercent }}%</span>
                    </div>
                    <el-progress
                      :percentage="tokenPercent"
                      :status="tokenPercent > 90 ? 'exception' : undefined"
                      :stroke-width="7"
                      :show-text="false"
                      class="budget-bar"
                    />
                  </div>

                  <!-- AI 赋能核心链路状态 (与右侧常驻调度高度平衡对齐) -->
                  <div class="llm-features-banner">
                    <div class="llm-features-title"><el-icon><Cpu /></el-icon> 当前 AI 引擎赋能场景</div>
                    <div class="llm-features-grid">
                      <div class="llm-feature-pill">
                        <span class="feature-dot" />
                        <span class="feature-text">买家意图识别与拟人应答</span>
                      </div>
                      <div class="llm-feature-pill">
                        <span class="feature-dot" />
                        <span class="feature-text">闲鱼好货多模态深度质检</span>
                      </div>
                      <div class="llm-feature-pill">
                        <span class="feature-dot" />
                        <span class="feature-text">转手套利文案自动创作</span>
                      </div>
                    </div>
                  </div>
                  <el-alert v-if="llm.error" :title="llm.error" type="error" :closable="false" show-icon class="mt-s" />
                </template>
              </div>
            </div>

            <!-- 右侧：系统后台调度常驻引擎 -->
            <div class="panel-box system-panel">
              <div class="panel-header">
                <div class="title-with-subtitle">
                  <div class="title-row-compact">
                    <span class="panel-title">后台服务与调度</span>
                    <span class="status-indicator-tag success">
                      <span class="pulse-dot-green" />
                      常驻正常
                    </span>
                  </div>
                </div>
                <div class="panel-action-group">
                  <button type="button" class="mini-capsule-btn primary" @click="router.push('/system')">
                    <el-icon><Tools /></el-icon>
                    <span>调度设置</span>
                    <el-icon class="arrow-ico"><Right /></el-icon>
                  </button>
                </div>
              </div>

              <div class="panel-body">
                <!-- 核心长连接与扫描守护卡片 (双列平铺) -->
                <div class="daemon-cards-grid">
                  <div class="daemon-card" :class="{ active: data?.system.im_running }">
                    <div class="daemon-icon-wrap im-theme">
                      <el-icon :size="18"><ChatDotRound /></el-icon>
                    </div>
                    <div class="daemon-info">
                      <div class="daemon-title-row">
                        <span class="daemon-name">IM 消息长连接</span>
                        <span class="daemon-status-pill" :class="data?.system.im_running ? 'running' : 'stopped'">
                          <span class="dot" />
                          {{ data?.system.im_running ? '监听中' : '未启动' }}
                        </span>
                      </div>
                      <div class="daemon-desc">买家即时沟通与秒级自动回复</div>
                    </div>
                  </div>

                  <div class="daemon-card active">
                    <div class="daemon-icon-wrap radar-theme">
                      <el-icon :size="18"><Aim /></el-icon>
                    </div>
                    <div class="daemon-info">
                      <div class="daemon-title-row">
                        <span class="daemon-name">选品监控定时引擎</span>
                        <span class="daemon-status-pill running">
                          <span class="dot" />
                          {{ data?.monitor_tasks ?? 0 }} 个生效
                        </span>
                      </div>
                      <div class="daemon-desc">全天候异步巡检闲鱼新上架好货</div>
                    </div>
                  </div>
                </div>

                <!-- 定时调度队列 (Cron 任务) -->
                <div v-if="data?.system.jobs.length" class="jobs-block">
                  <div class="jobs-header-row">
                    <div class="jobs-header-left">
                      <el-icon class="jobs-ico"><Timer /></el-icon>
                      <span class="jobs-title">常驻自动化巡检队列</span>
                    </div>
                    <span class="jobs-count-badge">已就绪 {{ data.system.jobs.length }} 项任务</span>
                  </div>

                  <div class="jobs-scroll-container">
                    <div v-for="j in data.system.jobs.slice(0, 6)" :key="j.id" class="job-item-card">
                      <div class="job-main-info">
                        <span class="job-category-tag" :class="getJobMeta(j.id).tagType">
                          {{ getJobMeta(j.id).category }}
                        </span>
                        <div class="job-names-wrap">
                          <span class="job-display-name">{{ getJobMeta(j.id).title }}</span>
                          <span class="job-code-name mono">{{ j.id }}</span>
                        </div>
                      </div>
                      <div class="job-next-run">
                        <span class="time-label">下次执行</span>
                        <span class="time-val mono">{{ fmtJobNextRun(j.next_run) }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
/* 全局页面视口高度自适应：占满可用高度，消除外部滚动条 */
.dashboard-page {
  height: calc(100vh - 56px - 40px);
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  animation: fadeIn 0.22s ease-out;
  overflow: hidden;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 顶部状态栏 */
.dash-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  flex-shrink: 0;
}
.header-left {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.page-title-text {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.header-meta {
  font-size: 12px;
  color: #94a3b8;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.live-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: #ecfdf5;
  border: 1px solid rgba(16, 185, 129, 0.25);
  color: #059669;
  font-size: 11px;
  font-weight: 500;
  padding: 1px 8px;
  border-radius: 999px;
}
.live-pulse {
  width: 5px;
  height: 5px;
  background: #10b981;
  border-radius: 50%;
  animation: pulseDot 2s infinite;
}
@keyframes pulseDot {
  0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
  70% { transform: scale(1); box-shadow: 0 0 0 5px rgba(16, 185, 129, 0); }
  100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}

/* 待办胶囊 */
.pending-alarm-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 3px 12px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.18s ease;
  font-weight: 500;
}
.pending-alarm-pill.active {
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #b45309;
}
.pending-alarm-pill.active:hover {
  background: #fef3c7;
  transform: translateY(-1px);
}
.pending-alarm-pill.calm {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #64748b;
}
.pending-alarm-pill.calm:hover {
  background: #f1f5f9;
}
.alarm-icon { color: #f59e0b; font-size: 14px; }
.check-icon { color: #10b981; font-size: 14px; }
.arrow-right { font-size: 11px; opacity: 0.7; }
.refresh-btn { border-color: #e2e8f0; font-weight: 500; }

/* 核心指标卡片矩阵 (紧凑高度 72px) */
.kpi-section {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 10px;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.kpi-card {
  background: linear-gradient(180deg, #ffffff 0%, #fbfcfe 100%);
  border: 1px solid var(--xh-border);
  border-top-width: 3px;
  border-radius: 9px;
  padding: 8px 12px 6px;
  cursor: pointer;
  transition: all 0.18s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
  display: flex;
  flex-direction: column;
}
.kpi-card:hover {
  transform: translateY(-2px);
  border-color: #cbd5e1;
  box-shadow: 0 6px 14px -2px rgba(0, 0, 0, 0.06);
}
.kpi-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 2px;
}
.kpi-label {
  font-size: 11.5px;
  font-weight: 500;
  color: #64748b;
}
.kpi-icon-bubble {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.kpi-value {
  font-size: 19px;
  font-weight: 700;
  letter-spacing: -0.4px;
  line-height: 1.2;
  margin-bottom: 2px;
  font-variant-numeric: tabular-nums;
}
.kpi-footer {
  font-size: 10.5px;
  color: #94a3b8;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
}
.kpi-arrow {
  opacity: 0;
  transition: opacity 0.15s, transform 0.15s;
  font-size: 10px;
}
.kpi-card:hover .kpi-arrow {
  opacity: 1;
  transform: translateX(2px);
}

/* 主工作区满高 Flex-1 布局 */
.dash-main-container {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* 现代化分段药丸导航栏 (Segmented Capsule Navigation) */
.dash-segmented-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 4px 6px;
  margin-bottom: 10px;
  flex-shrink: 0;
}
.seg-nav-list {
  display: flex;
  align-items: center;
  gap: 4px;
}
.seg-nav-item {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 34px;
  padding: 0 14px;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 500;
  color: #64748b;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 0.16s ease;
  user-select: none;
}
.seg-nav-item:hover {
  color: #1e293b;
  background: rgba(255, 255, 255, 0.5);
}
.seg-nav-item.is-active {
  background: #ffffff;
  color: #0f172a;
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08), 0 1px 2px rgba(15, 23, 42, 0.04);
}
.seg-nav-item.is-active .seg-icon {
  color: #10b981;
}
.seg-icon {
  font-size: 14px;
  color: #94a3b8;
  transition: color 0.16s;
}

/* 彻底解决拉伸变形的精致计数微徽章 */
.seg-counter-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 6px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  box-sizing: border-box;
  background: #e2e8f0;
  color: #475569;
}
.seg-nav-item.is-active .seg-counter-badge {
  background: #ecfdf5;
  color: #059669;
  border: 1px solid #a7f3d0;
}
.seg-tag-pill {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 999px;
  background: #e0f2fe;
  color: #0284c7;
  line-height: 1;
}
.seg-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.seg-status-dot.online {
  background: #10b981;
  box-shadow: 0 0 6px rgba(16, 185, 129, 0.6);
}
.seg-status-dot.offline {
  background: #cbd5e1;
}

/* 导航栏右侧状态与微指标 */
.seg-nav-meta {
  display: flex;
  align-items: center;
  padding-right: 6px;
}
.im-health-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: #475569;
  background: #ffffff;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}
.pulse-indicator {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.pulse-indicator.online {
  background: #10b981;
  box-shadow: 0 0 6px #10b981;
  animation: dotPulse 2s infinite ease-in-out;
}
.pulse-indicator.idle {
  background: #94a3b8;
}
@keyframes dotPulse {
  0% { transform: scale(0.9); opacity: 0.8; }
  50% { transform: scale(1.2); opacity: 1; }
  100% { transform: scale(0.9); opacity: 0.8; }
}
.meta-label {
  color: #64748b;
}
.meta-val {
  font-weight: 600;
  color: #0f172a;
}
.meta-sub {
  color: #10b981;
  font-weight: 500;
}

/* 视口容器 */
.dash-tabs-viewport {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.tab-pane-view {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
}

/* 网格双列撑满布局 */
.tab-grid-layout.two-cols {
  display: grid;
  grid-template-columns: 1.55fr 1fr;
  gap: 12px;
  height: 100%;
  flex: 1;
  min-height: 0;
}

/* 模块面板卡片通用样式 (撑满高度) */
.panel-box {
  background: #ffffff;
  border: 1px solid #eef2f6;
  border-radius: 10px;
  padding: 12px 16px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  flex-shrink: 0;
}
.title-with-subtitle {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.title-row-compact {
  display: flex;
  align-items: center;
  gap: 8px;
}
.panel-title {
  font-size: 14.5px;
  font-weight: 600;
  color: #1e293b;
  white-space: nowrap;
}
.panel-desc {
  font-size: 11.5px;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.status-indicator-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 500;
  padding: 1px 7px;
  border-radius: 999px;
  white-space: nowrap;
}
.status-indicator-tag.success {
  background: #ecfdf5;
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.25);
}
.status-indicator-tag.danger {
  background: #fef2f2;
  color: #dc2626;
  border: 1px solid rgba(239, 68, 68, 0.25);
}
.pulse-dot-green {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
  animation: pulseGreen 2s infinite;
}
@keyframes pulseGreen {
  0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
  70% { box-shadow: 0 0 0 4px rgba(16, 185, 129, 0); }
  100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}
.pulse-dot-red {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #ef4444;
}

/* 现代化胶囊操作按钮组（告别丑陋的裸露链接） */
.panel-action-group {
  display: flex;
  align-items: center;
  gap: 8px;
}
.mini-capsule-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.16s ease;
  user-select: none;
}
.mini-capsule-btn .arrow-ico {
  font-size: 11px;
  transition: transform 0.15s ease;
}
.mini-capsule-btn:hover .arrow-ico {
  transform: translateX(2px);
}
.mini-capsule-btn.primary {
  background: #ecfdf5;
  border-color: #a7f3d0;
  color: #047857;
}
.mini-capsule-btn.primary:hover {
  background: #10b981;
  border-color: #10b981;
  color: #ffffff;
  transform: translateY(-1px);
  box-shadow: 0 3px 8px rgba(16, 185, 129, 0.25);
}
.mini-capsule-btn.ghost {
  background: #f8fafc;
  border-color: #e2e8f0;
  color: #475569;
}
.mini-capsule-btn.ghost:hover {
  background: #f1f5f9;
  border-color: #cbd5e1;
  color: #0f172a;
  transform: translateY(-1px);
}


.panel-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 表格容器弹性撑满 */
.table-flex-wrap {
  flex: 1;
  min-height: 0;
}
.modern-account-table {
  border-radius: 6px;
}

/* 账号单元格 */
.account-profile {
  display: flex;
  align-items: center;
  gap: 8px;
}
.avatar-bubble {
  position: relative;
  width: 30px;
  height: 30px;
  border-radius: 7px;
  background: #ecfdf5;
  border: 1px solid #d1fae5;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
}
.status-dot-pulse {
  position: absolute;
  bottom: -2px;
  right: -2px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  border: 1px solid #fff;
}
.status-dot-pulse.online { background: #10b981; }
.status-dot-pulse.offline { background: #cbd5e1; }

.account-texts {
  display: flex;
  flex-direction: column;
}
.acc-nick {
  font-weight: 600;
  color: #1e293b;
  font-size: 12.5px;
  line-height: 1.3;
}
.acc-id {
  font-size: 10px;
  color: #94a3b8;
}

.health-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}
.health-bar {
  flex: 1;
}
.health-text {
  font-size: 11px;
  font-weight: 600;
  min-width: 32px;
}

.connection-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  background: #f8fafc;
}
.connection-tag .con-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
}
.connection-tag.is-connected {
  color: #059669;
  background: #ecfdf5;
}
.connection-tag.is-connected .con-dot {
  background: #10b981;
}
.connection-tag.is-disconnected {
  color: #94a3b8;
}
.connection-tag.is-disconnected .con-dot {
  background: #cbd5e1;
}

.panel-footer-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #f1f5f9;
  flex-shrink: 0;
}
.footer-tip {
  font-size: 11px;
  color: #94a3b8;
}

/* 账号表格紧凑自适应容器 */
.account-table-container {
  flex-shrink: 0;
}

/* 今日自动化运行效能指标矩阵 (填满下半部分) */
.automation-telemetry-section {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #f1f5f9;
}
.telemetry-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 8px;
  flex-shrink: 0;
}
.telemetry-title {
  font-size: 12.5px;
  font-weight: 600;
  color: #334155;
}
.telemetry-sub {
  font-size: 11px;
  color: #94a3b8;
}
.telemetry-grid {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  min-height: 0;
}
.telemetry-card {
  background: #f8fafc;
  border: 1px solid #eef2f6;
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  cursor: pointer;
  transition: all 0.18s ease;
}
.telemetry-card:hover {
  background: #ffffff;
  border-color: #cbd5e1;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
}
.tc-top {
  display: flex;
  align-items: center;
  gap: 6px;
}
.tc-label {
  font-size: 12px;
  font-weight: 600;
  color: #1e293b;
}
.tc-status {
  margin-left: auto;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 999px;
  font-weight: 500;
}
.tc-status.online {
  background: #ecfdf5;
  color: #059669;
}
.tc-status.off {
  color: var(--xh-muted);
  background: var(--xh-fill);
}
.tc-status.warn {
  color: var(--xh-warning-text);
  background: var(--el-color-warning-light-9);
}
.risk-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--xh-space-2);
  height: 100%;
  min-height: 200px;
  padding: var(--xh-space-5);
  text-align: center;
}
.risk-empty-icon {
  font-size: 32px;
  color: var(--xh-success);
}
.risk-empty-title {
  font-size: var(--xh-fs-lg);
  font-weight: 600;
  color: var(--xh-text);
}
.risk-empty-desc {
  margin: 0;
  max-width: 360px;
  font-size: var(--xh-fs-sm);
  line-height: 1.6;
  color: var(--xh-muted);
}
.tc-status.safe {
  background: #eff6ff;
  color: #2563eb;
}
.tc-val {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.3px;
  margin: 4px 0 2px;
}
.tc-unit {
  font-size: 11px;
  font-weight: 400;
  color: #64748b;
}
.tc-desc {
  font-size: 10.5px;
  color: #94a3b8;
  line-height: 1.4;
}

/* 右侧上下堆叠卡片 (待办中心 + 风控安全态势) */
.right-stack-col {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  min-height: 0;
}
.orders-pending-panel {
  flex-shrink: 0;
  height: auto !important;
  min-height: 72px;
  padding: 12px 16px;
  background: #ffffff;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  transition: all 0.18s ease;
}
.orders-pending-panel.has-alarm {
  background: #fffbeb;
  border-color: #fde68a;
}
.pending-panel-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  gap: 12px;
}
.pending-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.pending-icon-wrap {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.pending-icon-wrap.calm {
  background: #ecfdf5;
  color: #10b981;
}
.pending-icon-wrap.alarm {
  background: #fef3c7;
  color: #d97706;
}
.pending-status-title {
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
}
.pending-status-sub {
  font-size: 11.5px;
  color: #64748b;
  margin-top: 2px;
}
.pending-action-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--xh-primary, #10b981);
  font-weight: 600;
  flex-shrink: 0;
}

/* 安全防御态势大盘 (4维量化防御矩阵 + 立体自愈座舱，告别空洞死白) */

/* 下方中心自愈光晕与策略标签展示区 */

/* 风控时间线 */
.risk-timeline-container {
  flex: 1;
  overflow-y: auto;
  padding-right: 4px;
}
.compact-timeline {
  padding-left: 4px;
}
.timeline-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.acc-badge {
  font-weight: 600;
  font-size: 12px;
}
.timeline-reason {
  font-size: 11.5px;
  color: #64748b;
  margin-top: 2px;
}

/* Tab 2 找货面板满屏自适应 */
.tab-search-wrapper {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.search-hero-card {
  background: linear-gradient(135deg, #f0fdf4 0%, #ffffff 50%, #eff6ff 100%);
  border: 1px solid rgba(16, 185, 129, 0.25);
  border-radius: 10px;
  padding: 16px 20px;
  box-shadow: 0 2px 10px rgba(16, 185, 129, 0.04);
}
.hero-top-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}
.hero-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}
.search-badge-icon {
  width: 36px;
  height: 36px;
  background: #10b981;
  color: #ffffff;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3);
}
.hero-title {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.hero-tag {
  font-weight: 500;
}
.hero-subtitle {
  font-size: 12px;
  color: #64748b;
  margin: 3px 0 0;
}
.hero-input-box {
  flex: 1;
  min-width: 280px;
  max-width: 620px;
}
.custom-hero-input :deep(.el-input__wrapper) {
  border-radius: 8px 0 0 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
.hero-submit-btn {
  background: #10b981 !important;
  border-color: #10b981 !important;
  color: #ffffff !important;
  font-weight: 500;
  border-radius: 0 8px 8px 0;
}
.hero-hot-section {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed rgba(16, 185, 129, 0.2);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.hot-label {
  font-size: 11.5px;
  color: #64748b;
  font-weight: 500;
}
.hot-chips-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.hot-chip {
  font-size: 11px;
  background: #ffffff;
  border: 1px solid #d1fae5;
  color: #065f46;
  padding: 2px 9px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.hot-chip:hover {
  background: #10b981;
  border-color: #10b981;
  color: #ffffff;
  transform: translateY(-1px);
}
.jump-radar-btn {
  margin-left: auto;
  font-size: 12px;
  font-weight: 500;
}

/* 风控平稳运行态势卡片 (替代原死白空状态) */
.shield-active-state {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
}
.shield-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #ecfdf5;
  border: 1px solid rgba(16, 185, 129, 0.25);
  border-radius: 8px;
  padding: 10px 14px;
}
.shield-icon-circle {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #10b981;
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.shield-banner-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.shield-banner-title {
  font-size: 13px;
  font-weight: 600;
  color: #065f46;
}
.shield-banner-sub {
  font-size: 11px;
  color: #047857;
}
.shield-guard-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.guard-metric-card {
  background: #f8fafc;
  border: 1px solid #eef2f6;
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.gm-label {
  font-size: 11px;
  color: #64748b;
  font-weight: 500;
}
.gm-val {
  font-size: 13px;
  font-weight: 700;
  color: #1e293b;
}
.gm-tag {
  font-size: 10.5px;
  padding: 1px 6px;
  border-radius: 4px;
  display: inline-block;
  width: fit-content;
  font-weight: 500;
}
.gm-tag.ok {
  background: #ecfdf5;
  color: #059669;
}
.gm-tag.info {
  background: #eff6ff;
  color: #2563eb;
}
.shield-footer-tip {
  margin-top: auto;
  padding: 8px 12px;
  background: #fafbfc;
  border: 1px dashed #e2e8f0;
  border-radius: 8px;
  font-size: 11px;
  color: #64748b;
  line-height: 1.5;
}

/* 玩法卡片网格与发现大盘 */
.radar-workflow-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.workflow-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
  box-sizing: border-box;
}
.workflow-card:hover {
  transform: translateY(-2px);
  border-color: #cbd5e1;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.05);
}
.wf-icon-wrap {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.icon-blue { background: #eff6ff; color: #2563eb; }
.icon-purple { background: #f5f3ff; color: #7c3aed; }
.icon-emerald { background: #ecfdf5; color: #059669; }

.wf-content {
  flex: 1;
  min-width: 0;
}
.wf-name {
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 2px;
}
.wf-desc {
  font-size: 11px;
  color: #64748b;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.wf-action-pill {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  color: #10b981;
  background: #ecfdf5;
  border: 1px solid rgba(16, 185, 129, 0.2);
  padding: 3px 8px;
  border-radius: 999px;
  font-weight: 500;
  flex-shrink: 0;
}

/* 热门货源分类探索与捡漏技巧 */
.radar-discover-board {
  flex: 1;
  display: grid;
  grid-template-columns: 3fr 2fr;
  gap: 12px;
  min-height: 0;
}
.discover-col {
  background: #ffffff;
  border: 1px solid #eef2f6;
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
}
.discover-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 12px;
}
.d-title {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
}
.d-sub {
  font-size: 11px;
  color: #94a3b8;
}
.category-matrix {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cat-group {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cat-group-name {
  font-size: 11.5px;
  font-weight: 600;
  color: #475569;
  flex-shrink: 0;
  width: 66px;
}
.cat-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.d-chip {
  font-size: 11px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #334155;
  padding: 3px 9px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.d-chip:hover {
  background: #ecfdf5;
  border-color: #10b981;
  color: #059669;
}
.tips-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.tip-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 11.5px;
  color: #64748b;
  line-height: 1.5;
}
.tip-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #10b981;
  margin-top: 6px;
  flex-shrink: 0;
}
.tip-strong {
  color: #1e293b;
  font-weight: 600;
}

/* Tab 3 大模型与系统服务 */
.llm-details-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  margin-bottom: 12px;
}
.metric-card {
  background: #f8fafc;
  padding: 8px 12px;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.m-label {
  font-size: 11px;
  color: #64748b;
}
.m-val {
  font-size: 13px;
  color: #0f172a;
  font-weight: 500;
}
.m-val.highlight {
  font-weight: 700;
  color: #10b981;
}

.tier-models-box {
  background: #ffffff;
  border: 1px solid #f1f5f9;
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 10px;
}
.tier-title {
  font-size: 11px;
  color: #64748b;
  font-weight: 500;
  margin-bottom: 6px;
}
.tier-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tier-chip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11.5px;
  background: #f8fafc;
  padding: 3px 8px;
  border-radius: 4px;
}
.tier-name { color: #475569; }
.tier-val { color: #0f172a; font-size: 11px; }

.budget-progress-box {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #f1f5f9;
}
.budget-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
}
.small-muted { font-size: 11px; color: #94a3b8; }
.small-bold { font-size: 11px; font-weight: 600; }

.llm-features-banner {
  margin-top: 10px;
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid #eef2f6;
  border-radius: 8px;
}
.llm-features-title {
  font-size: 11px;
  font-weight: 600;
  color: #475569;
  margin-bottom: 6px;
}
.llm-features-grid {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.llm-feature-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: #334155;
}
.feature-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #10b981;
}

/* 核心后台长连接与扫描守护卡片 (双列平铺) */
.daemon-cards-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
  margin-bottom: 12px;
}
.daemon-card {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  transition: all 0.2s ease;
  position: relative;
  overflow: hidden;
}
.daemon-card:hover {
  border-color: #cbd5e1;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  transform: translateY(-1px);
}
.daemon-card.active {
  background: linear-gradient(180deg, #ffffff 0%, #fbfdfe 100%);
}
.daemon-icon-wrap {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: transform 0.2s ease;
}
.daemon-card:hover .daemon-icon-wrap {
  transform: scale(1.05);
}
.daemon-icon-wrap.im-theme {
  background: rgba(16, 185, 129, 0.1);
  color: #059669;
}
.daemon-icon-wrap.radar-theme {
  background: rgba(14, 165, 233, 0.1);
  color: #0284c7;
}
.daemon-info {
  flex: 1;
  min-width: 0;
}
.daemon-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 3px;
  gap: 4px;
}
.daemon-name {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.daemon-desc {
  font-size: 11px;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.daemon-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  font-weight: 500;
  flex-shrink: 0;
}
.daemon-status-pill.running {
  background: #ecfdf5;
  color: #047857;
  border: 1px solid rgba(16, 185, 129, 0.25);
}
.daemon-status-pill.running .dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #10b981;
}
.daemon-status-pill.stopped {
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid #e2e8f0;
}
.daemon-status-pill.stopped .dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #94a3b8;
}

/* 常驻自动化巡检队列 (Cron 任务卡片化) */
.jobs-block {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: #ffffff;
  border: 1px solid #eef2f6;
  border-radius: 8px;
  padding: 10px 12px;
}
.jobs-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  flex-shrink: 0;
}
.jobs-header-left {
  display: flex;
  align-items: center;
  gap: 6px;
}
.jobs-ico {
  font-size: 14px;
  color: #64748b;
}
.jobs-title {
  font-size: 12.5px;
  font-weight: 600;
  color: #334155;
}
.jobs-count-badge {
  font-size: 11px;
  color: #059669;
  background: #ecfdf5;
  border: 1px solid rgba(16, 185, 129, 0.2);
  padding: 1px 7px;
  border-radius: 999px;
  font-weight: 500;
}
.jobs-scroll-container {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding-right: 2px;
}
.job-item-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  padding: 6px 10px;
  border-radius: 6px;
  transition: all 0.15s ease;
}
.job-item-card:hover {
  background: #f1f5f9;
  border-color: #e2e8f0;
}
.job-main-info {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.job-category-tag {
  font-size: 10.5px;
  padding: 1px 5px;
  border-radius: 4px;
  font-weight: 600;
  flex-shrink: 0;
}
.job-category-tag.primary {
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid rgba(37, 99, 235, 0.15);
}
.job-category-tag.success {
  background: #ecfdf5;
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.15);
}
.job-category-tag.warning {
  background: #fffbeb;
  color: #d97706;
  border: 1px solid rgba(217, 119, 6, 0.15);
}
.job-category-tag.info {
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #e2e8f0;
}
.job-names-wrap {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}
.job-display-name {
  font-size: 12px;
  font-weight: 600;
  color: #1e293b;
  white-space: nowrap;
}
.job-code-name {
  font-size: 11px;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 140px;
}
.job-next-run {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.time-label {
  font-size: 10.5px;
  color: #94a3b8;
}
.time-val {
  font-size: 11.5px;
  color: #475569;
  font-weight: 500;
}

.ml-s { margin-left: 6px; }
.mt-s { margin-top: 10px; }
.mt-xs { margin-top: 4px; }
.inline-block { display: inline-block; }
</style>
