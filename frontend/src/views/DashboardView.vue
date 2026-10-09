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
const activeTab = ref('accounts')
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
      bg: '#eff6ff',
      path: '/messages/inbox',
    },
    {
      label: '自动回复',
      value: t?.messages_auto ?? 0,
      hint: '关键词 + AI 接待',
      icon: Lightning,
      color: '#8b5cf6',
      bg: '#f5f3ff',
      path: '/messages/rules',
    },
    {
      label: '自动发货',
      value: t?.deliveries ?? 0,
      hint: '已发出的发货卡密',
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
    <!-- 顶部极简状态栏 -->
    <div class="dash-head">
      <div class="head-left">
        <h2 class="title-with-badge">
          总览看板
          <span class="live-pill">
            <span class="live-pulse" />
            实时监控中
          </span>
        </h2>
        <span class="head-sub">零点基准自动统计 · 每分钟实时同步</span>
      </div>
      <div class="head-right">
        <!-- 待办订单报警胶囊 -->
        <div
          v-if="(data?.pending_manual_orders || 0) > 0"
          class="pending-alarm-pill"
          @click="router.push({ path: '/orders/list', query: { status: NEEDS_ACTION_STATUSES } })"
        >
          <el-icon><Warning /></el-icon>
          <span>{{ data?.pending_manual_orders }} 笔订单需处理</span>
          <el-icon><Right /></el-icon>
        </div>
        <el-button :icon="Refresh" :loading="loading" size="small" round @click="load">刷新数据</el-button>
      </div>
    </div>

    <!-- 核心指标卡片行 (紧凑 6 列布局) -->
    <el-row :gutter="10" class="kpi-row">
      <el-col v-for="k in kpis" :key="k.label" :xs="12" :sm="8" :lg="4">
        <div class="kpi-card" @click="router.push(k.path)">
          <div class="kpi-top">
            <span class="kpi-label">{{ k.label }}</span>
            <div class="kpi-icon-wrap" :style="{ color: k.color, backgroundColor: k.bg }">
              <el-icon :size="15"><component :is="k.icon" /></el-icon>
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

    <!-- 主工作区：Tab 切换栏，分类组织，一屏尽览 -->
    <el-tabs v-model="activeTab" class="dash-tabs" type="border-card">
      <!-- Tab 1: 闲鱼账号与风控防护 -->
      <el-tab-pane name="accounts">
        <template #label>
          <div class="tab-label-custom">
            <el-icon><UserFilled /></el-icon>
            <span>闲鱼账号与风控</span>
            <span v-if="data?.accounts.length" class="tab-count-badge">{{ data.accounts.length }}</span>
          </div>
        </template>

        <el-row :gutter="14" class="tab-fill-row">
          <!-- 账号状态表格 -->
          <el-col :xs="24" :lg="15">
            <div class="subcard">
              <div class="subcard-head">
                <div class="subcard-title-group">
                  <span class="subcard-title">闲鱼账号状态</span>
                  <span class="subcard-subtitle">已接入账号的消息通道与自动托管</span>
                </div>
                <el-button link type="primary" size="small" @click="router.push('/accounts')">管理全部账号 &gt;</el-button>
              </div>

              <div class="table-wrap">
                <el-table :data="data?.accounts || []" size="small" empty-text="还没有添加闲鱼账号" max-height="300">
                  <el-table-column label="账号昵称" min-width="150">
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

                  <el-table-column label="运行状态" width="100">
                    <template #default="{ row }">
                      <StatusTag :value="row.status" :map="accountStatusMap" />
                    </template>
                  </el-table-column>

                  <el-table-column label="健康度" min-width="130">
                    <template #default="{ row }">
                      <div class="health-wrap">
                        <el-progress
                          :percentage="row.health"
                          :color="healthColor(row.health)"
                          :stroke-width="6"
                          :show-text="false"
                          class="flex-1"
                        />
                        <span class="health-num" :style="{ color: healthColor(row.health) }">{{ row.health }}%</span>
                      </div>
                    </template>
                  </el-table-column>

                  <el-table-column label="长连接" width="85">
                    <template #default="{ row }">
                      <div class="im-status-pill" :class="row.im_connected ? 'online' : 'offline'">
                        <span class="dot" />
                        <span>{{ row.im_connected ? '在线' : '离线' }}</span>
                      </div>
                    </template>
                  </el-table-column>

                  <el-table-column label="自动回复" width="85">
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

                  <el-table-column label="自动发货" width="85">
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
            </div>
          </el-col>

          <!-- 待办 + 风控事件 -->
          <el-col :xs="24" :lg="9">
            <!-- 待办处理卡片 -->
            <div
              class="dash-pending-box"
              :class="{ active: (data?.pending_manual_orders || 0) > 0 }"
              @click="router.push({ path: '/orders/list', query: { status: NEEDS_ACTION_STATUSES } })"
            >
              <div class="pending-left">
                <div class="pending-icon-wrap" :class="{ warn: (data?.pending_manual_orders || 0) > 0 }">
                  <el-icon :size="18">
                    <component :is="(data?.pending_manual_orders || 0) > 0 ? Warning : CircleCheck" />
                  </el-icon>
                </div>
                <div>
                  <div class="pending-title">
                    {{ (data?.pending_manual_orders || 0) > 0 ? '有订单需人工处理' : '全部订单处理完毕' }}
                  </div>
                  <div class="pending-desc">
                    {{ (data?.pending_manual_orders || 0) > 0 ? '待人工 / 风控暂停 / 异常订单' : '当前无待人工发货或滞留订单' }}
                  </div>
                </div>
              </div>
              <div class="pending-count" :class="{ warn: (data?.pending_manual_orders || 0) > 0 }">
                {{ data?.pending_manual_orders ?? 0 }}
              </div>
            </div>

            <!-- 近 7 天风控与保护记录 -->
            <div class="subcard mt-s">
              <div class="subcard-head">
                <div class="subcard-title-group">
                  <span class="subcard-title">近 7 天风控防护记录</span>
                  <span class="subcard-subtitle">撞限流或滑块自愈情况</span>
                </div>
              </div>

              <div v-if="!data?.risk_events.length" class="empty-risk-state compact">
                <div class="empty-icon-shield">🛡️</div>
                <div class="empty-risk-title">近 7 天无异常风控事件</div>
                <div class="empty-risk-desc">拟人请求控频已开启，账号受全面安全防护</div>
              </div>
              <el-timeline v-else class="risk-timeline compact">
                <el-timeline-item
                  v-for="(r, i) in data.risk_events"
                  :key="r.id ?? i"
                  :timestamp="fmtTime(r.created_at)"
                  :type="r.resolved ? 'success' : r.state === 'circuit_open' ? 'danger' : 'warning'"
                >
                  <div class="risk-row">
                    <span class="risk-acc-name">{{ accountName(r.account_id) }}</span>
                    <StatusTag :value="r.state" :map="accountStatusMap" />
                    <el-tag v-if="r.resolved" size="small" type="success" effect="plain">已自愈</el-tag>
                  </div>
                  <div class="risk-reason">{{ r.reason || '短时访问频次过高' }}</div>
                  <el-link
                    v-if="r.punish_url && !r.resolved"
                    :href="r.punish_url"
                    target="_blank"
                    type="danger"
                    class="small mt-xs"
                  >
                    🔗 打开闲鱼验证解除 &gt;
                  </el-link>
                </el-timeline-item>
              </el-timeline>
            </div>
          </el-col>
        </el-row>
      </el-tab-pane>

      <!-- Tab 2: 闲鱼快速找货 (嵌入式 Hero 找货栏) -->
      <el-tab-pane name="search">
        <template #label>
          <div class="tab-label-custom">
            <el-icon><Search /></el-icon>
            <span>闲鱼实时找货</span>
          </div>
        </template>

        <div class="tab-search-container">
          <div class="quick-search-hero embedded">
            <div class="search-flex-row">
              <div class="search-desc">
                <div class="search-main-title">
                  <div class="search-icon-badge">
                    <el-icon :size="18"><Search /></el-icon>
                  </div>
                  <span>闲鱼全量一手货源实时搜索</span>
                  <el-tag size="small" effect="plain" type="success" class="ml-s">无需新建监控</el-tag>
                </div>
                <div class="search-sub-title">实时直搜闲鱼一手货源底价与成色，即搜即看，一键转手发品或加入监控</div>
              </div>
              <div class="search-input-wrap">
                <el-input
                  v-model="quickKeyword"
                  placeholder="输入商品名称/型号（如 iPhone 15、MacBook、Switch OLED），按回车立即找货"
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
                  v-for="k in ['MacBook M1', 'iPhone 15', 'Switch OLED', 'PS5', '显卡 RTX', 'iPad Air', 'AirPods Pro', '机械键盘']"
                  :key="k"
                  class="hot-pill"
                  @click="searchByKeyword(k)"
                >
                  {{ k }}
                </span>
              </div>
              <el-button link type="primary" size="small" class="more-search-link" @click="router.push('/radar/search')">
                进入完整选品雷达工作台 &gt;
              </el-button>
            </div>
          </div>

          <!-- 快速找货 3 步玩法引导 -->
          <div class="search-features-grid">
            <div class="sf-item" @click="router.push('/radar/search')">
              <div class="sf-icon sf-1">⚡</div>
              <div class="sf-text">
                <div class="sf-title">实时直搜</div>
                <div class="sf-desc">秒级拉取闲鱼第一手上架宝贝，避开倒爷二手加价</div>
              </div>
            </div>
            <div class="sf-item" @click="router.push('/radar/tasks')">
              <div class="sf-icon sf-2">🎯</div>
              <div class="sf-text">
                <div class="sf-title">自动监控</div>
                <div class="sf-desc">一键将心仪词设为后台定时任务，AI 替你全天候蹲守</div>
              </div>
            </div>
            <div class="sf-item" @click="router.push('/radar/results')">
              <div class="sf-icon sf-3">💎</div>
              <div class="sf-text">
                <div class="sf-title">一键转手发品</div>
                <div class="sf-desc">发现低价真漏直接转卖发品，自动加价并生成带货文案</div>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- Tab 3: AI 引擎与后台服务 -->
      <el-tab-pane name="system">
        <template #label>
          <div class="tab-label-custom">
            <el-icon><Cpu /></el-icon>
            <span>AI 引擎与系统服务</span>
            <span v-if="llm?.available" class="dot-online-mini" />
          </div>
        </template>

        <el-row :gutter="14" class="tab-fill-row">
          <!-- 大模型服务卡片 -->
          <el-col :xs="24" :lg="12">
            <div class="subcard">
              <div class="subcard-head">
                <div class="subcard-title-group">
                  <span class="subcard-title">AI 大模型服务</span>
                  <span class="subcard-subtitle">驱动自动客服、选品鉴定与发布文案</span>
                </div>
                <div class="flex items-center gap-2">
                  <el-tag v-if="llm" :type="llm.available ? 'success' : 'danger'" size="small" effect="light">
                    {{ llm.available ? '🟢 引擎就绪' : '🔴 连接异常' }}
                  </el-tag>
                  <el-button size="small" link type="primary" @click="router.push('/llm')">模型配置 &gt;</el-button>
                </div>
              </div>

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
                    <span class="llm-label">今日调用次数</span>
                    <span class="llm-val font-semibold">{{ llm.usage_today.calls }} 次</span>
                  </div>
                  <div class="llm-row">
                    <span class="llm-label">Token 消耗量</span>
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
            </div>
          </el-col>

          <!-- 系统后台服务与调度卡片 -->
          <el-col :xs="24" :lg="12">
            <div class="subcard">
              <div class="subcard-head">
                <div class="subcard-title-group">
                  <span class="subcard-title">系统后台服务与调度</span>
                  <span class="subcard-subtitle">IM 守护进程与常驻任务调度</span>
                </div>
                <el-button size="small" link type="primary" @click="router.push('/system')">系统设置 &gt;</el-button>
              </div>

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
            </div>
          </el-col>
        </el-row>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.dashboard-page {
  animation: fadeIn 0.25s ease-out;
  box-sizing: border-box;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 顶部状态栏 */
.dash-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.head-left {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.title-with-badge {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.head-sub {
  font-size: 12px;
  color: #94a3b8;
}
.head-right {
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
  padding: 1px 7px;
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

.pending-alarm-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #b45309;
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.15s;
}
.pending-alarm-pill:hover {
  background: #fef3c7;
  transform: translateY(-1px);
}

/* 核心指标卡片矩阵 (紧凑高度 ~70px) */
.kpi-row {
  margin-bottom: 10px;
}
.kpi-card {
  background: #ffffff;
  border: 1px solid var(--xh-border);
  border-radius: 9px;
  padding: 9px 12px 7px;
  cursor: pointer;
  transition: all 0.18s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
  display: flex;
  flex-direction: column;
}
.kpi-card:hover {
  transform: translateY(-2px);
  border-color: #cbd5e1;
  box-shadow: 0 4px 10px -2px rgba(0, 0, 0, 0.06);
}
.kpi-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 3px;
}
.kpi-label {
  font-size: 12px;
  font-weight: 500;
  color: #64748b;
}
.kpi-icon-wrap {
  width: 24px;
  height: 24px;
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
  margin-bottom: 3px;
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
  font-size: 10px;
}
.kpi-card:hover .arrow-hint {
  opacity: 1;
  transform: translateX(2px);
}

/* 主 Tab 容器 (全屏紧凑工作台) */
.dash-tabs {
  border-radius: 10px;
  border: 1px solid var(--xh-border);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
  background: #ffffff;
}
.dash-tabs :deep(.el-tabs__header) {
  background: #f8fafc;
  margin: 0;
  border-bottom: 1px solid var(--xh-border);
}
.dash-tabs :deep(.el-tabs__nav-wrap) {
  padding: 0 12px;
}
.dash-tabs :deep(.el-tabs__item) {
  height: 40px;
  line-height: 40px;
  font-size: 13.5px;
  color: #64748b;
  border: none !important;
  transition: all 0.15s;
}
.dash-tabs :deep(.el-tabs__item.is-active) {
  background: #ffffff;
  color: var(--xh-primary, #10b981) !important;
  font-weight: 600;
  border-bottom: 2px solid var(--xh-primary, #10b981) !important;
}
.dash-tabs :deep(.el-tabs__content) {
  padding: 12px 14px;
}

.tab-label-custom {
  display: flex;
  align-items: center;
  gap: 6px;
}
.tab-count-badge {
  font-size: 10px;
  background: #e2e8f0;
  color: #475569;
  padding: 1px 6px;
  border-radius: 999px;
  font-weight: 600;
}
.dot-online-mini {
  width: 6px;
  height: 6px;
  background: #10b981;
  border-radius: 50%;
  margin-left: 2px;
}

/* Tab 内卡片 */
.subcard {
  background: #ffffff;
  border: 1px solid #eef2f6;
  border-radius: 8px;
  padding: 12px 14px;
  box-sizing: border-box;
}
.subcard-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.subcard-title-group {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.subcard-title {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
}
.subcard-subtitle {
  font-size: 11px;
  color: #94a3b8;
}

/* 账号单元格 */
.account-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.acc-avatar-bubble {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: #ecfdf5;
  border: 1px solid #d1fae5;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
}
.acc-info {
  display: flex;
  flex-direction: column;
}
.acc-name {
  font-weight: 600;
  color: #1e293b;
  font-size: 12.5px;
  line-height: 1.3;
}
.acc-sub {
  font-size: 10px;
  color: #94a3b8;
}
.health-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
}
.health-num {
  font-size: 11.5px;
  font-weight: 600;
  min-width: 32px;
}

/* IM 状态指示 */
.im-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
}
.im-status-pill .dot {
  width: 5px;
  height: 5px;
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

/* 待办卡片 */
.dash-pending-box {
  background: #ffffff;
  border: 1px solid var(--xh-border);
  border-radius: 8px;
  padding: 10px 14px;
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
  gap: 10px;
}
.pending-icon-wrap {
  width: 32px;
  height: 32px;
  border-radius: 6px;
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
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
}
.pending-desc {
  font-size: 11px;
  color: #64748b;
  margin-top: 1px;
}
.pending-count {
  font-size: 22px;
  font-weight: 700;
  color: #94a3b8;
}
.pending-count.warn {
  color: #d97706;
}

/* 风控空状态 */
.empty-risk-state.compact {
  padding: 24px 12px;
  text-align: center;
}
.empty-icon-shield {
  font-size: 32px;
  margin-bottom: 4px;
}
.empty-risk-title {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}
.empty-risk-desc {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 2px;
}

/* 风控时间线 */
.risk-timeline.compact {
  padding-left: 4px;
  max-height: 200px;
  overflow-y: auto;
}
.risk-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.risk-acc-name {
  font-weight: 600;
  font-size: 12px;
}
.risk-reason {
  font-size: 11.5px;
  color: #64748b;
  margin-top: 2px;
}

/* Tab 2 找货面板样式 */
.tab-search-container {
  padding: 6px 4px;
}
.quick-search-hero.embedded {
  background: linear-gradient(135deg, #ffffff 0%, #f4fbf7 60%, #eefbf3 100%);
  border: 1px solid rgba(16, 185, 129, 0.3);
  border-radius: 10px;
  padding: 16px 20px;
  box-shadow: 0 2px 8px rgba(16, 185, 129, 0.04);
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
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
  display: flex;
  align-items: center;
  gap: 8px;
}
.search-icon-badge {
  width: 28px;
  height: 28px;
  background: #10b981;
  color: #ffffff;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.search-sub-title {
  font-size: 12px;
  color: #64748b;
  margin-top: 3px;
}
.search-input-wrap {
  flex: 1;
  min-width: 280px;
  max-width: 600px;
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
  padding: 2px 9px;
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

/* 玩法卡片网格 */
.search-features-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-top: 14px;
}
.sf-item {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.sf-item:hover {
  transform: translateY(-1px);
  border-color: #cbd5e1;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
}
.sf-icon {
  font-size: 24px;
}
.sf-title {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
}
.sf-desc {
  font-size: 11px;
  color: #64748b;
  margin-top: 2px;
}

/* Tab 3 大模型与系统服务 */
.llm-info-grid {
  display: flex;
  flex-direction: column;
  gap: 7px;
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
  padding: 1px 6px;
  border-radius: 4px;
  color: #334155;
  font-size: 11px;
}
.llm-divider {
  height: 1px;
  background: #f1f5f9;
  margin: 3px 0;
}
.token-progress-wrap {
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px dashed var(--xh-border);
}
.token-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 3px;
}

.system-status-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid #f1f5f9;
}
.sys-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.sys-label {
  color: #64748b;
}
.jobs-list-wrap {
  margin-top: 8px;
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

.ml-s { margin-left: 6px; }
.mt-s { margin-top: 10px; }
.mt-xs { margin-top: 4px; }
.font-semibold { font-weight: 600; }
.smaller { font-size: 10px; }
</style>
