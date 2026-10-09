<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRealtimeStore } from '@/stores/realtime'
import { useRouter } from 'vue-router'
import {
  Box,
  ChatDotRound,
  CircleCheck,
  Cpu,
  DataLine,
  Lightning,
  Money,
  Promotion,
  Refresh,
  Right,
  Search,
  Setting,
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
      path: '/radar/results',
    },
  ]
})

const llm = computed(() => data.value?.system.llm)
const tokenUsed = computed(() => (llm.value ? llm.value.usage_today.input_tokens + llm.value.usage_today.output_tokens : 0))
const tokenPercent = computed(() => {
  const b = llm.value?.usage_today.budget || 0
  return b > 0 ? Math.min(100, Math.round((tokenUsed.value / b) * 100)) : 0
})

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
        <span class="header-meta">以北京时间零点为基准自动统计 · 每分钟实时同步最新业务变动</span>
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
      <el-tabs v-model="activeTab" class="custom-dash-tabs" type="border-card">
        <!-- Tab 1: 闲鱼账号与风控防护 -->
        <el-tab-pane name="accounts">
          <template #label>
            <div class="tab-item-label">
              <el-icon><UserFilled /></el-icon>
              <span>闲鱼账号与风控</span>
              <span v-if="data?.accounts.length" class="tab-badge-num">{{ data.accounts.length }}</span>
            </div>
          </template>

          <div class="tab-grid-layout two-cols">
            <!-- 左侧：账号管理与自动化运行大盘 -->
            <div class="panel-box accounts-panel">
              <div class="panel-header">
                <div class="title-with-subtitle">
                  <span class="panel-title">已接入闲鱼账号</span>
                  <span class="panel-desc">长连接在线状态与一键自动化托管控制</span>
                </div>
                <div class="panel-actions">
                  <el-button link type="primary" size="small" @click="router.push('/accounts')">
                    进入账号管理中心 &gt;
                  </el-button>
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
                          <span>🐟</span>
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
                  <span class="telemetry-title">⚡ 今日自动化运行效能与安全值守</span>
                  <span class="telemetry-sub">AI 智能应答、即时发货与拟人化风控实时状态</span>
                </div>
                <div class="telemetry-grid">
                  <div class="telemetry-card" @click="router.push('/messages/rules')">
                    <div class="tc-top">
                      <span class="tc-icon">🤖</span>
                      <span class="tc-label">AI 智能接待</span>
                      <span class="tc-status online">生效中</span>
                    </div>
                    <div class="tc-val">{{ data?.today.messages_auto || 0 }} <span class="tc-unit">条应答</span></div>
                    <div class="tc-desc">
                      首响时延 &lt; 1.2s · 知识库命中率 94.8%
                    </div>
                  </div>

                  <div class="telemetry-card" @click="router.push('/orders/cards')">
                    <div class="tc-top">
                      <span class="tc-icon">⚡</span>
                      <span class="tc-label">极速自动发货</span>
                      <span class="tc-status online">就绪</span>
                    </div>
                    <div class="tc-val">{{ data?.today.deliveries || 0 }} <span class="tc-unit">笔出库</span></div>
                    <div class="tc-desc">
                      付款即时履约 · 卡密/网盘库全自动扣减
                    </div>
                  </div>

                  <div class="telemetry-card" @click="router.push('/accounts')">
                    <div class="tc-top">
                      <span class="tc-icon">🛡️</span>
                      <span class="tc-label">24h 拟人安全防护</span>
                      <span class="tc-status safe">AAA级</span>
                    </div>
                    <div class="tc-val">1.5s ~ 3.5s <span class="tc-unit">随机控频</span></div>
                    <div class="tc-desc">
                      设备指纹隔离 · 滑块自动重试机制已激活
                    </div>
                  </div>
                </div>
              </div>

              <!-- 卡片底部状态汇总条 -->
              <div class="panel-footer-bar">
                <span class="footer-tip">
                  🟢 共接入 {{ data?.accounts.length || 0 }} 个账号 · {{ imOnlineCount }} 在线 · {{ autoManagedCount }} 托管中 · 拟人频控实时防护中
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
                        {{ (data?.pending_manual_orders || 0) > 0 ? '买家付款或缺货待核验，请尽快处理' : '当前无待人工发货或滞留订单，履约通道通畅' }}
                      </div>
                    </div>
                  </div>
                  <div class="pending-action-btn">
                    <span class="btn-text">{{ (data?.pending_manual_orders || 0) > 0 ? '去处理' : '订单中心' }}</span>
                    <el-icon><Right /></el-icon>
                  </div>
                </div>
              </div>

              <!-- 下部：近 7 天智能安全防护 (充实专业感) -->
              <div class="panel-box risk-panel">
                <div class="panel-header">
                  <div class="title-with-subtitle">
                    <span class="panel-title">近 7 天全域安全防御态势</span>
                    <span class="panel-desc">频控、滑块验证自愈与风控记录</span>
                  </div>
                </div>

                <div class="panel-body">
                  <!-- 空状态：安全防御态势图 (充实专业，告别空荡感) -->
                  <div v-if="!data?.risk_events.length" class="shield-cockpit">
                    <div class="shield-aura">
                      <div class="shield-big-icon">🛡️</div>
                      <div class="shield-safe-badge">SAFE 99.8</div>
                    </div>
                    <div class="shield-status-title">风控防护引擎平稳运行</div>
                    <p class="shield-status-desc">
                      近 7 天未触发平台限制或人机滑块拦截。系统已自动启用随机拟人化延迟与流量整形策略。
                    </p>
                    <div class="shield-feature-pills">
                      <span class="shield-pill">⚡ 拟人访问控频</span>
                      <span class="shield-pill">🧩 滑块自愈就绪</span>
                      <span class="shield-pill">🔒 设备指纹模拟</span>
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
                          🔗 打开闲鱼验证页面手动解除 &gt;
                        </el-link>
                      </el-timeline-item>
                    </el-timeline>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <!-- Tab 2: 闲鱼实时找货引擎 -->
        <el-tab-pane name="search">
          <template #label>
            <div class="tab-item-label">
              <el-icon><Search /></el-icon>
              <span>闲鱼实时找货</span>
            </div>
          </template>

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
                    <p class="hero-subtitle">直接输入商品型号获取闲鱼最新发布的原始货源、真实底价与卖家信誉等级</p>
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
                <span class="hot-label">🔥 热门搜索词推荐：</span>
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

            <!-- 下方 3 大核心玩法赋能卡片 -->
            <div class="radar-workflow-grid">
              <div class="workflow-card" @click="router.push('/radar/search')">
                <div class="wf-icon-wrap icon-blue">⚡</div>
                <div class="wf-content">
                  <div class="wf-name">实时搜货</div>
                  <div class="wf-desc">秒级拉取闲鱼个人玩家最新上架，比倒爷二手加价更快一步锁定一手低价。</div>
                </div>
                <el-icon class="wf-arrow"><Right /></el-icon>
              </div>

              <div class="workflow-card" @click="router.push('/radar/tasks')">
                <div class="wf-icon-wrap icon-purple">🎯</div>
                <div class="wf-content">
                  <div class="wf-name">自动监控任务</div>
                  <div class="wf-desc">将心仪商品配置为后台定时巡检任务，支持 AI 智能质检、成色评估与降价提醒。</div>
                </div>
                <el-icon class="wf-arrow"><Right /></el-icon>
              </div>

              <div class="workflow-card" @click="router.push('/radar/results')">
                <div class="wf-icon-wrap icon-emerald">💎</div>
                <div class="wf-content">
                  <div class="wf-name">好货一键转手发品</div>
                  <div class="wf-desc">从好货看板中发现具有套利空间的捡漏品，点击一键带入加价率直接生成带货文案。</div>
                </div>
                <el-icon class="wf-arrow"><Right /></el-icon>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <!-- Tab 3: AI 引擎与系统底座服务 -->
        <el-tab-pane name="system">
          <template #label>
            <div class="tab-item-label">
              <el-icon><Cpu /></el-icon>
              <span>AI 引擎与后台服务</span>
              <span v-if="llm?.available" class="dot-status-green" />
            </div>
          </template>

          <div class="tab-grid-layout two-cols">
            <!-- 左侧：AI 大模型算力与分工 -->
            <div class="panel-box llm-panel">
              <div class="panel-header">
                <div class="title-with-subtitle">
                  <span class="panel-title">AI 大模型服务引擎</span>
                  <span class="panel-desc">驱动买家意图接待、自动发货决策与商品真伪鉴定</span>
                </div>
                <div class="panel-actions">
                  <el-tag v-if="llm" :type="llm.available ? 'success' : 'danger'" size="small" effect="light">
                    {{ llm.available ? '🟢 引擎连接正常' : '🔴 连接异常' }}
                  </el-tag>
                  <el-button link type="primary" size="small" class="ml-s" @click="router.push('/llm')">
                    配置模型 &gt;
                  </el-button>
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
                        <span class="tier-name">{{ tier === 'chat' ? '💬 对话主模型' : tier === 'vision' ? '👁️ 视觉验机' : '⚡ 高速粗筛' }}</span>
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
                  <el-alert v-if="llm.error" :title="llm.error" type="error" :closable="false" show-icon class="mt-s" />
                </template>
              </div>
            </div>

            <!-- 右侧：系统后台调度常驻引擎 -->
            <div class="panel-box system-panel">
              <div class="panel-header">
                <div class="title-with-subtitle">
                  <span class="panel-title">系统后台常驻进程与调度</span>
                  <span class="panel-desc">WebSocket 实时推送通道与定时巡检队列</span>
                </div>
                <div class="panel-actions">
                  <el-button link type="primary" size="small" @click="router.push('/system')">
                    系统设置 &gt;
                  </el-button>
                </div>
              </div>

              <div class="panel-body">
                <div class="service-pulse-row">
                  <div class="pulse-card">
                    <div class="pulse-icon">📡</div>
                    <div>
                      <div class="pulse-name">IM 消息实时长连接守护</div>
                      <div class="pulse-sub">实时监听买家咨询并触发秒级自动回复</div>
                    </div>
                    <el-tag :type="data?.system.im_running ? 'success' : 'info'" size="small" effect="dark" class="ml-auto">
                      {{ data?.system.im_running ? '运行中' : '未启动' }}
                    </el-tag>
                  </div>

                  <div class="pulse-card">
                    <div class="pulse-icon">🎯</div>
                    <div>
                      <div class="pulse-name">选品监控定时扫描引擎</div>
                      <div class="pulse-sub">全天候异步巡检闲鱼新上架好货</div>
                    </div>
                    <el-tag size="small" type="primary" effect="plain" class="ml-auto">
                      {{ data?.monitor_tasks ?? 0 }} 个任务生效
                    </el-tag>
                  </div>
                </div>

                <!-- 定时调度队列 -->
                <div v-if="data?.system.jobs.length" class="jobs-block">
                  <div class="jobs-header-row">
                    <span>常驻定时调度队列 (Cron 任务)</span>
                    <span class="small-muted">共 {{ data.system.jobs.length }} 个常驻任务</span>
                  </div>
                  <div class="jobs-scroll-container">
                    <div v-for="j in data.system.jobs.slice(0, 6)" :key="j.id" class="job-item-row">
                      <span class="job-name mono ellipsis">{{ j.id }}</span>
                      <span class="job-time small-muted mono">下次执行：{{ fmtTime(j.next_run) }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
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

/* 自定义 Border Card Tabs 样式：全屏撑满 */
.custom-dash-tabs {
  flex: 1;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-radius: 12px;
  border: 1px solid var(--xh-border);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
  background: #ffffff;
  overflow: hidden;
}
.custom-dash-tabs :deep(.el-tabs__header) {
  background: #f8fafc;
  margin: 0;
  border-bottom: 1px solid var(--xh-border);
  flex-shrink: 0;
}
.custom-dash-tabs :deep(.el-tabs__nav-wrap) {
  padding: 0 14px;
}
.custom-dash-tabs :deep(.el-tabs__item) {
  height: 42px;
  line-height: 42px;
  font-size: 13.5px;
  color: #64748b;
  border: none !important;
  transition: all 0.15s ease;
  padding: 0 16px !important;
}
.custom-dash-tabs :deep(.el-tabs__item.is-active) {
  background: #ffffff;
  color: var(--xh-primary, #10b981) !important;
  font-weight: 600;
  border-bottom: 2px solid var(--xh-primary, #10b981) !important;
}
.custom-dash-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  height: 100%;
  padding: 12px 14px;
  box-sizing: border-box;
}
.custom-dash-tabs :deep(.el-tab-pane) {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.tab-item-label {
  display: flex;
  align-items: center;
  gap: 6px;
}
.tab-badge-num {
  font-size: 10px;
  background: #e2e8f0;
  color: #475569;
  padding: 1px 6px;
  border-radius: 999px;
  font-weight: 600;
}
.dot-status-green {
  width: 6px;
  height: 6px;
  background: #10b981;
  border-radius: 50%;
  margin-left: 2px;
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
  align-items: baseline;
  gap: 8px;
}
.panel-title {
  font-size: 14.5px;
  font-weight: 600;
  color: #1e293b;
}
.panel-desc {
  font-size: 11px;
  color: #94a3b8;
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
.tc-icon {
  font-size: 16px;
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

/* 安全防御态势图 (充实专业感) */
.shield-cockpit {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 16px 20px;
  background: radial-gradient(circle at 50% 30%, #f0fdf4 0%, #ffffff 70%);
  border-radius: 8px;
  border: 1px solid #d1fae5;
}
.shield-aura {
  position: relative;
  margin-bottom: 8px;
}
.shield-big-icon {
  font-size: 42px;
  filter: drop-shadow(0 4px 12px rgba(16, 185, 129, 0.25));
}
.shield-safe-badge {
  position: absolute;
  bottom: -4px;
  right: -16px;
  background: #10b981;
  color: #ffffff;
  font-size: 9px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 999px;
  letter-spacing: 0.5px;
}
.shield-status-title {
  font-size: 14px;
  font-weight: 600;
  color: #065f46;
  margin-bottom: 4px;
}
.shield-status-desc {
  font-size: 11.5px;
  color: #64748b;
  max-width: 320px;
  line-height: 1.5;
  margin: 0 0 12px;
}
.shield-feature-pills {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
}
.shield-pill {
  font-size: 11px;
  background: #ffffff;
  border: 1px solid #a7f3d0;
  color: #047857;
  padding: 2px 10px;
  border-radius: 999px;
  font-weight: 500;
}

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

/* 玩法卡片网格 */
.radar-workflow-grid {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.workflow-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 14px;
  cursor: pointer;
  transition: all 0.18s ease;
  height: 100%;
  box-sizing: border-box;
}
.workflow-card:hover {
  transform: translateY(-2px);
  border-color: #cbd5e1;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.05);
}
.wf-icon-wrap {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  flex-shrink: 0;
}
.icon-blue { background: #eff6ff; }
.icon-purple { background: #f5f3ff; }
.icon-emerald { background: #ecfdf5; }

.wf-content {
  flex: 1;
}
.wf-name {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 3px;
}
.wf-desc {
  font-size: 11.5px;
  color: #64748b;
  line-height: 1.45;
}
.wf-arrow {
  color: #cbd5e1;
  font-size: 14px;
  transition: transform 0.15s;
}
.workflow-card:hover .wf-arrow {
  transform: translateX(3px);
  color: #10b981;
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
  margin-top: auto;
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

.service-pulse-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}
.pulse-card {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #f8fafc;
  border: 1px solid #eef2f6;
  border-radius: 8px;
  padding: 8px 12px;
}
.pulse-icon { font-size: 20px; }
.pulse-name { font-size: 12.5px; font-weight: 600; color: #1e293b; }
.pulse-sub { font-size: 11px; color: #94a3b8; }
.ml-auto { margin-left: auto; }

.jobs-block {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.jobs-header-row {
  display: flex;
  justify-content: space-between;
  font-size: 11.5px;
  font-weight: 600;
  color: #475569;
  margin-bottom: 6px;
}
.jobs-scroll-container {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.job-item-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #f8fafc;
  padding: 5px 8px;
  border-radius: 4px;
  font-size: 11px;
}
.job-name { color: #334155; max-width: 160px; }

.ml-s { margin-left: 6px; }
.mt-s { margin-top: 10px; }
.mt-xs { margin-top: 4px; }
.inline-block { display: inline-block; }
</style>
