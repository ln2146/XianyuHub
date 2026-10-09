<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRealtimeStore } from '@/stores/realtime'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { getDashboard, type Dashboard } from '@/api/dashboard'
import StatusTag from '@/components/StatusTag.vue'
import { NEEDS_ACTION_STATUSES, accountStatusMap, fmtMoney, fmtTime, orderStatusMap } from '@/utils/format'

const router = useRouter()
const realtime = useRealtimeStore()
const data = ref<Dashboard | null>(null)
const loading = ref(false)
let timer: number | undefined

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
  // 每分钟自动刷新；账号 / 订单状态变化时实时刷新
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
    { label: '今日买家消息', value: t?.messages_in ?? 0, hint: `人工回复 ${t?.messages_manual ?? 0}` },
    { label: '自动回复', value: t?.messages_auto ?? 0, hint: '关键词 + AI + 默认回复' },
    { label: '自动发货', value: t?.deliveries ?? 0, hint: '今日发出的发货消息' },
    { label: '今日订单', value: orders, hint: '含待付款' },
    { label: '今日 GMV', value: fmtMoney(t?.gmv ?? 0), hint: '不含待付款 / 退款 / 关闭' },
    { label: '选品推荐', value: radar, hint: `推荐 ${t?.radar.recommend || 0} · 有条件 ${t?.radar.conditional || 0}` },
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
  if (h >= 80) return '#67c23a'
  if (h >= 50) return '#e6a23c'
  return '#f56c6c'
}
</script>

<template>
  <div v-loading="loading && !data" class="page">
    <div class="page-head">
      <div>
        <h2>总览</h2>
        <div class="sub">今日数据以北京时间零点为界，每分钟自动刷新</div>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-row :gutter="12">
      <el-col v-for="k in kpis" :key="k.label" :xs="12" :sm="8" :lg="4">
        <el-card shadow="never" class="kpi">
          <div class="kpi-label">{{ k.label }}</div>
          <div class="kpi-value">{{ k.value }}</div>
          <div class="kpi-hint">{{ k.hint }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12">
      <el-col :xs="24" :lg="16">
        <el-card shadow="never" class="block">
          <template #header>
            <div class="card-head">
              <span>账号健康</span>
              <el-button link type="primary" @click="router.push('/accounts')">管理账号</el-button>
            </div>
          </template>
          <div class="table-wrap">
            <el-table :data="data?.accounts || []" size="small" empty-text="还没有添加闲鱼账号">
              <el-table-column label="账号" prop="nickname" min-width="120" />
              <el-table-column label="状态" width="110">
                <template #default="{ row }"><StatusTag :value="row.status" :map="accountStatusMap" /></template>
              </el-table-column>
              <el-table-column label="健康度" min-width="140">
                <template #default="{ row }">
                  <el-progress :percentage="row.health" :color="healthColor(row.health)" :stroke-width="8" />
                </template>
              </el-table-column>
              <el-table-column label="IM" width="80">
                <template #default="{ row }">
                  <el-tag :type="row.im_connected ? 'success' : 'info'" size="small">{{ row.im_connected ? '在线' : '离线' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="自动回复" width="90">
                <template #default="{ row }">{{ row.auto_reply ? '开' : '关' }}</template>
              </el-table-column>
              <el-table-column label="自动发货" width="90">
                <template #default="{ row }">{{ row.auto_delivery ? '开' : '关' }}</template>
              </el-table-column>
            </el-table>
          </div>
        </el-card>

        <el-card shadow="never" class="block">
          <template #header>
            <div class="card-head">
              <span>近 7 天风控事件</span>
            </div>
          </template>
          <el-empty v-if="!data?.risk_events.length" description="暂无风控事件" :image-size="60" />
          <el-timeline v-else class="risk-list">
            <el-timeline-item
              v-for="(r, i) in data.risk_events"
              :key="r.id ?? i"
              :timestamp="fmtTime(r.created_at)"
              :type="r.resolved ? 'success' : r.state === 'circuit_open' ? 'danger' : 'warning'"
            >
              <div class="risk-row">
                <strong>{{ accountName(r.account_id) }}</strong>
                <StatusTag :value="r.state" :map="accountStatusMap" />
                <el-tag v-if="r.resolved" size="small" type="success" effect="plain">已处理</el-tag>
              </div>
              <div class="muted small">{{ r.reason || '无说明' }}</div>
              <el-link
                v-if="r.punish_url && !r.resolved"
                :href="r.punish_url"
                target="_blank"
                type="danger"
                class="small"
              >打开验证页面</el-link>
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="8">
        <el-card shadow="never" class="block pending" @click="router.push({ path: '/orders/list', query: { status: NEEDS_ACTION_STATUSES } })">
          <div class="kpi-label">需要我处理的订单</div>
          <div class="kpi-value" :class="{ warn: (data?.pending_manual_orders || 0) > 0 }">
            {{ data?.pending_manual_orders ?? 0 }}
          </div>
          <div class="kpi-hint">待人工 / 风控暂停 / 发货失败，点击查看</div>
        </el-card>

        <el-card shadow="never" class="block">
          <template #header>
            <div class="card-head">
              <span>大模型状态</span>
              <div>
                <el-tag v-if="llm" :type="llm.available ? 'success' : 'danger'" size="small">
                  {{ llm.available ? '可用' : '不可用' }}
                </el-tag>
                <el-button size="small" link type="primary" @click="router.push('/llm')">配置</el-button>
              </div>
            </div>
          </template>
          <template v-if="llm">
            <el-descriptions :column="1" size="small" border>
              <el-descriptions-item label="提供方">{{ llm.provider || '-' }}</el-descriptions-item>
              <el-descriptions-item label="配置来源">
                <el-tag v-if="llm.source === 'env'" size="small" type="warning" effect="plain">环境变量</el-tag>
                <span v-else>{{ llm.source || '-' }}</span>
              </el-descriptions-item>
              <el-descriptions-item v-for="(m, tier) in llm.models" :key="tier" :label="`模型 ${tier}`">
                <span class="mono small">{{ m || '-' }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="今日调用">{{ llm.usage_today.calls }} 次</el-descriptions-item>
              <el-descriptions-item label="今日 Token">
                {{ tokenUsed.toLocaleString() }}
                <span v-if="llm.usage_today.budget" class="muted"> / {{ llm.usage_today.budget.toLocaleString() }}</span>
              </el-descriptions-item>
            </el-descriptions>
            <el-progress v-if="llm.usage_today.budget" :percentage="tokenPercent" class="mt" :status="tokenPercent > 90 ? 'exception' : undefined" />
            <el-alert v-if="llm.error" :title="llm.error" type="error" :closable="false" show-icon class="mt" />
          </template>
        </el-card>

        <el-card shadow="never" class="block">
          <template #header><span>系统</span></template>
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="IM 网关">
              <el-tag :type="data?.system.im_running ? 'success' : 'info'" size="small">{{ data?.system.im_running ? '运行中' : '未运行' }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="选品任务">{{ data?.monitor_tasks ?? 0 }} 个</el-descriptions-item>
            <el-descriptions-item label="今日订单状态">
              <template v-if="data && Object.keys(data.today.orders).length">
                <el-tag v-for="(n, st) in data.today.orders" :key="st" size="small" effect="plain" class="mr">
                  {{ orderStatusMap[st]?.label || st }} {{ n }}
                </el-tag>
              </template>
              <span v-else class="muted">-</span>
            </el-descriptions-item>
          </el-descriptions>
          <div v-if="data?.system.jobs.length" class="jobs">
            <div class="muted small">定时任务（{{ data.system.jobs.length }}）</div>
            <div v-for="j in data.system.jobs.slice(0, 8)" :key="j.id" class="job">
              <span class="mono small ellipsis">{{ j.id }}</span>
              <span class="muted small">{{ fmtTime(j.next_run) }}</span>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.kpi {
  margin-bottom: 12px;
}
.kpi-label {
  color: var(--xh-muted);
  font-size: 13px;
}
.kpi-value {
  font-size: 26px;
  font-weight: 700;
  margin: 6px 0 4px;
  font-variant-numeric: tabular-nums;
}
.kpi-value.warn {
  color: #e6a23c;
}
.kpi-hint {
  color: var(--xh-muted);
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.block {
  margin-bottom: 12px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.pending {
  cursor: pointer;
}
.risk-list {
  padding-left: 4px;
  max-height: 360px;
  overflow: auto;
}
.risk-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.mt {
  margin-top: 12px;
}
.mr {
  margin: 2px 4px 2px 0;
}
.jobs {
  margin-top: 12px;
}
.job {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 0;
  border-bottom: 1px dashed var(--xh-border);
}
</style>
