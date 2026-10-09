<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRealtimeStore } from '@/stores/realtime'
import { useRouter } from 'vue-router'
import {
  Box,
  ChatDotRound,
  CircleCheck,
  DataLine,
  Lightning,
  Money,
  Promotion,
  Refresh,
  Right,
  Search,
  Warning,
} from '@element-plus/icons-vue'
import { getDashboard, type Dashboard } from '@/api/dashboard'
import StatusTag from '@/components/StatusTag.vue'
import { NEEDS_ACTION_STATUSES, accountStatusMap, fmtMoney, fmtTime } from '@/utils/format'

const router = useRouter()
const realtime = useRealtimeStore()
const data = ref<Dashboard | null>(null)
const loading = ref(false)
const quickKeyword = ref('')
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
      bg: '#eff6ff',
      path: '/messages/inbox',
    },
    {
      label: '自动回复',
      value: t?.messages_auto ?? 0,
      hint: '关键词 + AI 智能接待',
      icon: Lightning,
      color: '#8b5cf6',
      bg: '#f5f3ff',
      path: '/messages/rules',
    },
    {
      label: '自动发货',
      value: t?.deliveries ?? 0,
      hint: '已自动发出的发货卡密',
      icon: Promotion,
      color: '#10b981',
      bg: '#ecfdf5',
      path: '/orders/cards',
    },
    {
      label: '今日订单',
      value: orders,
      hint: '含待付款全量订单',
      icon: Box,
      color: '#f97316',
      bg: '#fff7ed',
      path: '/orders/list',
    },
    {
      label: '今日 GMV',
      value: fmtMoney(t?.gmv ?? 0),
      hint: '成交金额 (扣除退款)',
      icon: Money,
      color: '#eab308',
      bg: '#fefce8',
      path: '/orders/list',
    },
    {
      label: '选品推荐',
      value: radar,
      hint: `捡漏 ${t?.radar.recommend || 0} · 需核 ${t?.radar.conditional || 0}`,
      icon: DataLine,
      color: '#06b6d4',
      bg: '#ecfeff',
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
    <div class="page-head">
      <div>
        <h2 class="title-with-badge">
          总览看板
          <span class="live-pill">
            <span class="live-pulse" />
            实时监控中
          </span>
        </h2>
        <div class="sub">数据以北京时间零点为基准自动统计，每分钟自动同步最新变动</div>
      </div>
      <div class="toolbar">
        <el-button :icon="Refresh" :loading="loading" round @click="load">刷新数据</el-button>
      </div>
    </div>

    <!-- 核心指标卡片矩阵 -->
    <el-row :gutter="12" class="kpi-row">
      <el-col v-for="k in kpis" :key="k.label" :xs="12" :sm="8" :lg="4">
        <div class="kpi-card" @click="router.push(k.path)">
          <div class="kpi-top">
            <span class="kpi-label">{{ k.label }}</span>
            <div class="kpi-icon-wrap" :style="{ color: k.color, backgroundColor: k.bg }">
              <el-icon :size="18"><component :is="k.icon" /></el-icon>
            </div>
          </div>
          <div class="kpi-value" :style="{ color: k.value === '¥0' || k.value === 0 ? '#1f2937' : k.color }">
            {{ k.value }}
          </div>
          <div class="kpi-hint">
            <span>{{ k.hint }}</span>
            <el-icon class="arrow-hint"><Right /></el-icon>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 闲鱼商品快速找货 Hero 栏 -->
    <div class="quick-search-hero">
      <div class="search-flex-row">
        <div class="search-desc">
          <div class="search-main-title">
            <div class="search-icon-badge">
              <el-icon :size="18"><Search /></el-icon>
            </div>
            <span>闲鱼实时找货</span>
            <el-tag size="small" effect="plain" type="success" class="ml-s">无需新建监控</el-tag>
          </div>
          <div class="search-sub-title">实时直搜闲鱼一手货源底价与成色，即搜即看，一键转手或监控</div>
        </div>
        <div class="search-input-wrap">
          <el-input
            v-model="quickKeyword"
            placeholder="输入商品名称/型号（如 iPhone 15、MacBook、Switch），按回车立即搜索"
            size="large"
            clearable
            class="hero-search-input"
            @keyup.enter="goToSearch"
          >
            <template #append>
              <el-button type="primary" :icon="Search" class="hero-search-btn" @click="goToSearch">
                立即找货
              </el-button>
            </template>
          </el-input>
        </div>
      </div>
      <div class="hot-search-row">
        <span class="hot-title">🔥 热门搜索推荐：</span>
        <div class="hot-tags-group">
          <span
            v-for="k in ['MacBook M1', 'iPhone 15', 'Switch OLED', 'PS5', '显卡 RTX', 'iPad Air', 'AirPods Pro']"
            :key="k"
            class="hot-pill"
            @click="searchByKeyword(k)"
          >
            {{ k }}
          </span>
        </div>
        <el-button link type="primary" size="small" class="more-search-link" @click="router.push('/radar/search')">
          进入完整找货工作台 &gt;
        </el-button>
      </div>
    </div>

    <!-- 主数据区域 -->
    <el-row :gutter="14">
      <!-- 左栏：账号健康 + 风控历史 -->
      <el-col :xs="24" :lg="16">
        <!-- 账号健康卡片 -->
        <el-card shadow="never" class="dash-card mb-m">
          <template #header>
            <div class="card-head">
              <div class="card-title-group">
                <span class="card-title">闲鱼账号状态</span>
                <span class="card-subtitle">已接入账号的消息通道与自动托管</span>
              </div>
              <el-button link type="primary" @click="router.push('/accounts')">管理全部账号 &gt;</el-button>
            </div>
          </template>

          <div class="table-wrap">
            <el-table :data="data?.accounts || []" size="default" empty-text="还没有添加闲鱼账号">
              <el-table-column label="账号昵称" min-width="170">
                <template #default="{ row }">
                  <div class="account-cell">
                    <div class="acc-avatar-bubble">🐟</div>
                    <div class="acc-info">
                      <div class="acc-name">{{ row.remark || row.nickname || '闲鱼账号' }}</div>
                      <div class="acc-sub mono">{{ row.nickname }}</div>
                    </div>
                  </div>
                </template>
              </el-table-column>

              <el-table-column label="运行状态" width="110">
                <template #default="{ row }">
                  <StatusTag :value="row.status" :map="accountStatusMap" />
                </template>
              </el-table-column>

              <el-table-column label="账号健康度" min-width="150">
                <template #default="{ row }">
                  <div class="health-wrap">
                    <el-progress
                      :percentage="row.health"
                      :color="healthColor(row.health)"
                      :stroke-width="7"
                      :show-text="false"
                      class="flex-1"
                    />
                    <span class="health-num" :style="{ color: healthColor(row.health) }">{{ row.health }}%</span>
                  </div>
                </template>
              </el-table-column>

              <el-table-column label="长连接" width="95">
                <template #default="{ row }">
                  <div class="im-status-pill" :class="row.im_connected ? 'online' : 'offline'">
                    <span class="dot" />
                    <span>{{ row.im_connected ? '在线' : '离线' }}</span>
                  </div>
                </template>
              </el-table-column>

              <el-table-column label="自动回复" width="95">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.auto_reply ? 'success' : 'info'" effect="light">
                    {{ row.auto_reply ? '已开启' : '未开启' }}
                  </el-tag>
                </template>
              </el-table-column>

              <el-table-column label="自动发货" width="95">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.auto_delivery ? 'success' : 'info'" effect="light">
                    {{ row.auto_delivery ? '已开启' : '未开启' }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-card>

        <!-- 风控事件卡片 -->
        <el-card shadow="never" class="dash-card">
          <template #header>
            <div class="card-head">
              <div class="card-title-group">
                <span class="card-title">近 7 天风控与保护记录</span>
                <span class="card-subtitle">记录撞限流、滑块验证或环境检测事件</span>
              </div>
            </div>
          </template>

          <div v-if="!data?.risk_events.length" class="empty-risk-state">
            <div class="empty-icon-shield">🛡️</div>
            <div class="empty-risk-title">健康平稳，近 7 天无异常风控事件</div>
            <div class="empty-risk-desc">系统已开启拟人请求控频与轻度限流自动自愈策略，账号安全受全面保护</div>
          </div>
          <el-timeline v-else class="risk-timeline">
            <el-timeline-item
              v-for="(r, i) in data.risk_events"
              :key="r.id ?? i"
              :timestamp="fmtTime(r.created_at)"
              :type="r.resolved ? 'success' : r.state === 'circuit_open' ? 'danger' : 'warning'"
            >
              <div class="risk-row">
                <span class="risk-acc-name">{{ accountName(r.account_id) }}</span>
                <StatusTag :value="r.state" :map="accountStatusMap" />
                <el-tag v-if="r.resolved" size="small" type="success" effect="plain">已解除自愈</el-tag>
              </div>
              <div class="risk-reason">{{ r.reason || '短时访问频次过高或接口临时挤爆' }}</div>
              <el-link
                v-if="r.punish_url && !r.resolved"
                :href="r.punish_url"
                target="_blank"
                type="danger"
                class="small mt-xs"
              >
                🔗 打开闲鱼安全验证页面解除 &gt;
              </el-link>
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-col>

      <!-- 右栏：待办提醒 + 大模型 + 系统状态 -->
      <el-col :xs="24" :lg="8">
        <!-- 待办处理卡片 -->
        <div
          class="dash-pending-box"
          :class="{ active: (data?.pending_manual_orders || 0) > 0 }"
          @click="router.push({ path: '/orders/list', query: { status: NEEDS_ACTION_STATUSES } })"
        >
          <div class="pending-left">
            <div class="pending-icon-wrap" :class="{ warn: (data?.pending_manual_orders || 0) > 0 }">
              <el-icon :size="22">
                <component :is="(data?.pending_manual_orders || 0) > 0 ? Warning : CircleCheck" />
              </el-icon>
            </div>
            <div>
              <div class="pending-title">
                {{ (data?.pending_manual_orders || 0) > 0 ? '有订单需人工处理' : '全部订单处理完毕' }}
              </div>
              <div class="pending-desc">
                {{ (data?.pending_manual_orders || 0) > 0 ? '待人工 / 风控暂停 / 发货失败' : '当前无待人工发货或异常滞留订单' }}
              </div>
            </div>
          </div>
          <div class="pending-count" :class="{ warn: (data?.pending_manual_orders || 0) > 0 }">
            {{ data?.pending_manual_orders ?? 0 }}
          </div>
        </div>

        <!-- 大模型服务卡片 -->
        <el-card shadow="never" class="dash-card mb-m">
          <template #header>
            <div class="card-head">
              <div class="card-title-group">
                <span class="card-title">AI 大模型服务</span>
              </div>
              <div>
                <el-tag v-if="llm" :type="llm.available ? 'success' : 'danger'" size="small" effect="light">
                  {{ llm.available ? '🟢 引擎就绪' : '🔴 连接异常' }}
                </el-tag>
                <el-button size="small" link type="primary" class="ml-s" @click="router.push('/llm')">配置</el-button>
              </div>
            </div>
          </template>

          <template v-if="llm">
            <div class="llm-info-grid">
              <div class="llm-row">
                <span class="llm-label">服务提供方</span>
                <span class="llm-val">{{ llm.provider || '未配置' }}</span>
              </div>
              <div class="llm-row">
                <span class="llm-label">配置来源</span>
                <el-tag v-if="llm.source === 'env'" size="small" type="warning" effect="plain">环境变量</el-tag>
                <span v-else class="llm-val">{{ llm.source || '-' }}</span>
              </div>
              <div class="llm-divider" />
              <div v-for="(m, tier) in llm.models" :key="tier" class="llm-row">
                <span class="llm-label">{{ tier === 'chat' ? '对话主模型' : tier === 'vision' ? '视觉解析' : '高速过滤' }}</span>
                <span class="llm-model-tag mono">{{ m || '-' }}</span>
              </div>
              <div class="llm-divider" />
              <div class="llm-row">
                <span class="llm-label">今日调用</span>
                <span class="llm-val font-semibold">{{ llm.usage_today.calls }} 次</span>
              </div>
              <div class="llm-row">
                <span class="llm-label">Token 消耗</span>
                <span class="llm-val font-semibold">{{ tokenUsed.toLocaleString() }}</span>
              </div>
            </div>

            <div v-if="llm.usage_today.budget" class="token-progress-wrap">
              <div class="token-head">
                <span class="small muted">今日预算限额</span>
                <span class="small mono">{{ tokenPercent }}%</span>
              </div>
              <el-progress
                :percentage="tokenPercent"
                :status="tokenPercent > 90 ? 'exception' : undefined"
                :stroke-width="6"
                :show-text="false"
              />
            </div>
            <el-alert v-if="llm.error" :title="llm.error" type="error" :closable="false" show-icon class="mt-s" />
          </template>
        </el-card>

        <!-- 系统与后台运行卡片 -->
        <el-card shadow="never" class="dash-card">
          <template #header>
            <div class="card-head">
              <div class="card-title-group">
                <span class="card-title">系统后台服务</span>
              </div>
              <el-button size="small" link type="primary" @click="router.push('/system')">设置</el-button>
            </div>
          </template>

          <div class="system-status-grid">
            <div class="sys-item">
              <span class="sys-label">IM 消息守护进程</span>
              <el-tag :type="data?.system.im_running ? 'success' : 'info'" size="small">
                {{ data?.system.im_running ? '正常运行' : '未启动' }}
              </el-tag>
            </div>
            <div class="sys-item">
              <span class="sys-label">自动选品监控任务</span>
              <span class="font-semibold">{{ data?.monitor_tasks ?? 0 }} 个开启</span>
            </div>
          </div>

          <div v-if="data?.system.jobs.length" class="jobs-list-wrap">
            <div class="jobs-header">
              <span>定时常驻调度（{{ data.system.jobs.length }}）</span>
            </div>
            <div class="jobs-scroll-box">
              <div v-for="j in data.system.jobs.slice(0, 6)" :key="j.id" class="job-chip">
                <span class="mono ellipsis job-id">{{ j.id }}</span>
                <span class="muted smaller">{{ fmtTime(j.next_run) }}</span>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.dashboard-page {
  animation: fadeIn 0.25s ease-out;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.title-with-badge {
  display: flex;
  align-items: center;
  gap: 12px;
}
.live-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #ecfdf5;
  border: 1px solid rgba(16, 185, 129, 0.2);
  color: #059669;
  font-size: 11px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 999px;
}
.live-pulse {
  width: 6px;
  height: 6px;
  background: #10b981;
  border-radius: 50%;
  animation: pulseDot 2s infinite;
}
@keyframes pulseDot {
  0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
  70% { transform: scale(1); box-shadow: 0 0 0 5px rgba(16, 185, 129, 0); }
  100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}

/* KPI 卡片 */
.kpi-row {
  margin-bottom: 14px;
}
.kpi-card {
  background: #ffffff;
  border: 1px solid var(--xh-border);
  border-radius: 10px;
  padding: 14px 14px 12px;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  display: flex;
  flex-direction: column;
  height: 100%;
}
.kpi-card:hover {
  transform: translateY(-2px);
  border-color: #cbd5e1;
  box-shadow: 0 6px 14px -2px rgba(0, 0, 0, 0.07);
}
.kpi-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.kpi-label {
  font-size: 13px;
  font-weight: 500;
  color: #64748b;
}
.kpi-icon-wrap {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.kpi-value {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.5px;
  line-height: 1.2;
  margin-bottom: 6px;
  font-variant-numeric: tabular-nums;
}
.kpi-hint {
  font-size: 11px;
  color: #94a3b8;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
}
.arrow-hint {
  opacity: 0;
  transition: opacity 0.15s, transform 0.15s;
  font-size: 11px;
}
.kpi-card:hover .arrow-hint {
  opacity: 1;
  transform: translateX(2px);
}

/* 快速找货 Hero 栏 */
.quick-search-hero {
  margin-bottom: 16px;
  background: linear-gradient(135deg, #ffffff 0%, #f4fbf7 60%, #eefbf3 100%);
  border: 1px solid rgba(16, 185, 129, 0.3);
  border-radius: 12px;
  padding: 16px 20px;
  box-shadow: 0 2px 8px rgba(16, 185, 129, 0.05);
}
.search-flex-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}
.search-desc {
  min-width: 240px;
}
.search-main-title {
  font-size: 17px;
  font-weight: 700;
  color: #0f172a;
  display: flex;
  align-items: center;
  gap: 10px;
}
.search-icon-badge {
  width: 30px;
  height: 30px;
  background: #10b981;
  color: #ffffff;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 6px rgba(16, 185, 129, 0.3);
}
.search-sub-title {
  font-size: 12px;
  color: #64748b;
  margin-top: 4px;
}
.search-input-wrap {
  flex: 1;
  min-width: 280px;
  max-width: 640px;
}
.hero-search-input :deep(.el-input__wrapper) {
  border-radius: 8px 0 0 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
.hero-search-btn {
  background: #10b981 !important;
  border-color: #10b981 !important;
  color: #ffffff !important;
  font-weight: 500;
  border-radius: 0 8px 8px 0;
}
.hot-search-row {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed rgba(16, 185, 129, 0.2);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.hot-title {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
}
.hot-tags-group {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.hot-pill {
  font-size: 11px;
  background: #ffffff;
  border: 1px solid #d1fae5;
  color: #065f46;
  padding: 2px 10px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.15s;
}
.hot-pill:hover {
  background: #10b981;
  border-color: #10b981;
  color: #ffffff;
  transform: translateY(-1px);
}
.more-search-link {
  margin-left: auto;
  font-size: 12px;
  font-weight: 500;
}

/* 卡片与模块通用 */
.dash-card {
  border-radius: 10px;
  border-color: var(--xh-border);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}
.mb-m {
  margin-bottom: 14px;
}
.ml-s {
  margin-left: 6px;
}
.mt-xs {
  margin-top: 4px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card-title-group {
  display: flex;
  flex-direction: column;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
}
.card-subtitle {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 2px;
}

/* 账号单元格 */
.account-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}
.acc-avatar-bubble {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: #ecfdf5;
  border: 1px solid #d1fae5;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
}
.acc-info {
  display: flex;
  flex-direction: column;
}
.acc-name {
  font-weight: 600;
  color: #1e293b;
  font-size: 13px;
}
.acc-sub {
  font-size: 11px;
  color: #94a3b8;
}
.health-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}
.health-num {
  font-size: 12px;
  font-weight: 600;
  min-width: 36px;
}

/* IM 状态指示 */
.im-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
}
.im-status-pill .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.im-status-pill.online {
  color: #059669;
}
.im-status-pill.online .dot {
  background: #10b981;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2);
}
.im-status-pill.offline {
  color: #94a3b8;
}
.im-status-pill.offline .dot {
  background: #cbd5e1;
}

/* 风控空状态 */
.empty-risk-state {
  padding: 30px 16px;
  text-align: center;
}
.empty-icon-shield {
  font-size: 38px;
  margin-bottom: 8px;
}
.empty-risk-title {
  font-size: 14px;
  font-weight: 600;
  color: #334155;
}
.empty-risk-desc {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 4px;
}

/* 风控时间线 */
.risk-timeline {
  padding-left: 6px;
  max-height: 280px;
  overflow-y: auto;
}
.risk-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.risk-acc-name {
  font-weight: 600;
  font-size: 13px;
}
.risk-reason {
  font-size: 12px;
  color: #64748b;
  margin-top: 3px;
}

/* 待办处理卡片 */
.dash-pending-box {
  background: #ffffff;
  border: 1px solid var(--xh-border);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  transition: all 0.15s;
}
.dash-pending-box:hover {
  transform: translateY(-1px);
  border-color: #cbd5e1;
}
.dash-pending-box.active {
  background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
  border-color: #fde68a;
}
.pending-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.pending-icon-wrap {
  width: 38px;
  height: 38px;
  border-radius: 8px;
  background: #f1f5f9;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
}
.pending-icon-wrap.warn {
  background: #fef08a;
  color: #b45309;
}
.pending-title {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
}
.pending-desc {
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
}
.pending-count {
  font-size: 26px;
  font-weight: 700;
  color: #94a3b8;
}
.pending-count.warn {
  color: #d97706;
}

/* 大模型信息网格 */
.llm-info-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.llm-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
}
.llm-label {
  color: #64748b;
}
.llm-val {
  color: #1e293b;
}
.llm-model-tag {
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
  color: #334155;
  font-size: 11px;
}
.llm-divider {
  height: 1px;
  background: #f1f5f9;
  margin: 4px 0;
}
.token-progress-wrap {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--xh-border);
}
.token-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
}

/* 系统运行网格 */
.system-status-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
  font-size: 13px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f1f5f9;
}
.sys-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.sys-label {
  color: #64748b;
  font-size: 12px;
}
.jobs-list-wrap {
  margin-top: 10px;
}
.jobs-header {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 500;
  margin-bottom: 6px;
}
.jobs-scroll-box {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.job-chip {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #f8fafc;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
}
.job-id {
  color: #475569;
  max-width: 140px;
}
.font-semibold {
  font-weight: 600;
}
.smaller {
  font-size: 10px;
}
</style>

