<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRealtimeStore } from '@/stores/realtime'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import { closeHold, deliverOrder, getOrder, listOrders, syncOrders, type DeliveryRecord, type Order } from '@/api/order'
import StatusTag from '@/components/StatusTag.vue'
import ListPager from '@/components/ListPager.vue'
import { useAccountsStore } from '@/stores/accounts'
import { useMobile } from '@/composables/useMobile'
import { fmtMoney, fmtTime, itemUrl, orderStatusMap } from '@/utils/format'

const route = useRoute()
const accounts = useAccountsStore()
const realtime = useRealtimeStore()
const isMobile = useMobile()

const orders = ref<Order[]>([])
const loading = ref(false)
const syncing = ref(false)
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const busy = reactive<Record<string, boolean>>({})
const filter = reactive({
  account_id: undefined as number | undefined,
  status: (typeof route.query.status === 'string' ? route.query.status : '') as string,
  q: '',
})

async function load(p = 1) {
  loading.value = true
  try {
    const res = await listOrders({
      account_id: filter.account_id,
      status: filter.status || undefined,
      q: filter.q.trim() || undefined,
      limit: pageSize.value,
      offset: (p - 1) * pageSize.value,
    })
    // 当前页被删空（如筛选条件变化导致总数减少）时回退到最后一页
    const last = Math.max(1, Math.ceil(res.total / pageSize.value))
    if (!res.items.length && p > last) return await load(last)
    orders.value = res.items
    total.value = res.total
    page.value = p
  } finally {
    loading.value = false
  }
}

let unsubscribe: (() => void) | undefined
let debounce: number | undefined
onMounted(() => {
  load()
  accounts.load().catch(() => undefined)
  // 订单状态变化实时刷新当前页
  unsubscribe = realtime.subscribe((ev) => {
    if (ev.event === 'order') {
      window.clearTimeout(debounce)
      debounce = window.setTimeout(() => load(page.value), 1000)
    }
  })
})
onBeforeUnmount(() => {
  window.clearTimeout(debounce)
  unsubscribe?.()
})

async function sync() {
  if (!filter.account_id) {
    ElMessage.warning('请先选择要同步的账号')
    return
  }
  syncing.value = true
  try {
    const r = await syncOrders(filter.account_id)
    const names: Record<string, string> = { created: '新增', paid: '新付款' }
    ElMessage.success(`同步完成：${Object.entries(r).map(([k, v]) => `${names[k] || k} ${v}`).join('，') || '无变化'}`)
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    syncing.value = false
  }
}

const deliveryModeLabel: Record<string, string> = {
  send_then_confirm: '先发消息后确认',
  confirm_then_send: '先确认后发消息',
  send_only: '仅发消息',
}

const canDeliver = (o: Order) => ['paid', 'risk_hold', 'deliver_failed', 'manual'].includes(o.status)

async function deliver(o: Order) {
  await ElMessageBox.confirm(
    `将立即为订单 ${o.order_id}（${o.buyer_nick || '买家'}，${fmtMoney(o.amount)}）发货：按卡券绑定发送内容并在闲鱼确认发货。此操作跳过发货前风控检查。`,
    '手动发货',
    { type: 'warning', confirmButtonText: '确认发货' },
  )
  busy[`d-${o.id}`] = true
  try {
    const r = await deliverOrder(o.id)
    if (r.ok) ElMessage.success('发货成功')
    else ElMessage.error(`发货失败：${r.error || orderStatusMap[r.status]?.label || r.status}`)
    await load(page.value)
    if (detail.open && detail.order?.id === o.id) await openDetail(o)
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[`d-${o.id}`] = false
  }
}

async function toManual(o: Order) {
  await ElMessageBox.confirm('将该风控暂停的订单转为人工处理（不再自动发货），确定？', '转人工', { type: 'warning' })
  busy[`h-${o.id}`] = true
  try {
    const r = await closeHold(o.id)
    ElMessage.success(`已转为：${orderStatusMap[r.status]?.label || r.status}`)
    await load(page.value)
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[`h-${o.id}`] = false
  }
}

// ---------------------------------------------------------------- 详情
const detail = reactive({ open: false, loading: false, order: null as Order | null, deliveries: [] as DeliveryRecord[] })

async function openDetail(o: Order) {
  Object.assign(detail, { open: true, loading: true, order: o, deliveries: [] })
  try {
    const r = await getOrder(o.id)
    detail.order = r.order
    detail.deliveries = r.deliveries
  } finally {
    detail.loading = false
  }
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>订单发货 · 订单</h2>
        <div class="sub">买家付款后按卡券绑定自动发货（需在账号设置中开启）。风控暂停 / 发货失败的订单需人工处理。</div>
      </div>
    </div>

    <el-card shadow="never" class="filters">
      <div class="toolbar">
        <el-select v-model="filter.account_id" clearable placeholder="全部账号" class="w180" @change="load()">
          <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
        </el-select>
        <el-button type="primary" :icon="Refresh" :loading="syncing" :disabled="!filter.account_id" @click="sync">同步订单</el-button>
        <el-select v-model="filter.status" clearable placeholder="全部状态" class="w140" @change="load()">
          <el-option v-for="(v, k) in orderStatusMap" :key="k" :value="k" :label="v.label" />
        </el-select>
        <el-input v-model="filter.q" placeholder="订单号 / 商品 / 买家" clearable class="w200" :prefix-icon="Search" @keyup.enter="load()" @clear="load()" />
        <el-button :icon="Refresh" :loading="loading" @click="load(page)">刷新</el-button>
      </div>
    </el-card>

    <el-card shadow="never">
      <div class="table-wrap">
        <el-table v-loading="loading" :data="orders" empty-text="暂无订单" @row-dblclick="(r: Order) => openDetail(r)">
          <el-table-column label="订单" min-width="200">
            <template #default="{ row }">
              <el-link type="primary" @click="openDetail(row as Order)">{{ row.order_id }}</el-link>
              <div class="muted small">{{ accounts.nameOf(row.account_id) }} · {{ fmtTime(row.created_at) }}</div>
            </template>
          </el-table-column>
          <el-table-column label="商品" min-width="200">
            <template #default="{ row }">
              <div class="ellipsis">{{ row.item_title || row.item_id || '-' }}</div>
              <div v-if="row.spec_value" class="muted small">{{ row.spec_name || '规格' }}：{{ row.spec_value }}</div>
            </template>
          </el-table-column>
          <el-table-column label="买家" min-width="110">
            <template #default="{ row }">{{ row.buyer_nick || row.buyer_id || '-' }}</template>
          </el-table-column>
          <el-table-column label="金额" width="110">
            <template #default="{ row }">
              <span class="price">{{ fmtMoney(row.amount) }}</span>
              <span v-if="row.quantity > 1" class="muted small"> ×{{ row.quantity }}</span>
              <el-tag v-if="row.is_bargain" size="small" effect="plain" class="ml">议价</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="130">
            <template #default="{ row }">
              <StatusTag :value="row.status" :map="orderStatusMap" />
              <el-tooltip v-if="row.fail_reason" :content="row.fail_reason">
                <div class="small err ellipsis">{{ row.fail_reason }}</div>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="付款 / 发货" width="150">
            <template #default="{ row }">
              <div class="small">{{ fmtTime(row.paid_at) }}</div>
              <div class="small muted">{{ fmtTime(row.delivered_at) }}</div>
            </template>
          </el-table-column>
          <el-table-column label="操作" :width="isMobile ? 100 : 200" :fixed="isMobile ? undefined : 'right'">
            <template #default="{ row }">
              <div class="ops">
                <el-button size="small" @click="openDetail(row as Order)">详情</el-button>
                <el-button v-if="canDeliver(row as Order)" size="small" type="primary" :loading="busy[`d-${row.id}`]" @click="deliver(row as Order)">手动发货</el-button>
                <el-button v-if="row.status === 'risk_hold'" size="small" type="warning" plain :loading="busy[`h-${row.id}`]" @click="toManual(row as Order)">转人工</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <ListPager v-model:page="page" v-model:page-size="pageSize" :total="total" :disabled="loading" @change="load(page)" />
    </el-card>

    <el-drawer v-model="detail.open" title="订单详情" size="560px">
      <div v-loading="detail.loading">
        <template v-if="detail.order">
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="订单号"><span class="mono">{{ detail.order.order_id }}</span></el-descriptions-item>
            <el-descriptions-item label="状态">
              <StatusTag :value="detail.order.status" :map="orderStatusMap" />
              <span v-if="detail.order.remote_status" class="muted small ml">闲鱼：{{ detail.order.remote_status }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="账号">{{ accounts.nameOf(detail.order.account_id) }}</el-descriptions-item>
            <el-descriptions-item label="商品">
              <el-link v-if="detail.order.item_id" :href="itemUrl(detail.order.item_id)" target="_blank" type="primary">{{ detail.order.item_title || detail.order.item_id }}</el-link>
              <span v-else>{{ detail.order.item_title || '-' }}</span>
            </el-descriptions-item>
            <el-descriptions-item v-if="detail.order.spec_value" label="规格">{{ detail.order.spec_name }}：{{ detail.order.spec_value }}</el-descriptions-item>
            <el-descriptions-item label="买家">{{ detail.order.buyer_nick || '-' }} <span class="muted small">{{ detail.order.buyer_id }}</span></el-descriptions-item>
            <el-descriptions-item label="金额">{{ fmtMoney(detail.order.amount) }} × {{ detail.order.quantity }}{{ detail.order.is_bargain ? '（议价成交）' : '' }}</el-descriptions-item>
            <el-descriptions-item label="下单时间">{{ fmtTime(detail.order.created_at, true) }}</el-descriptions-item>
            <el-descriptions-item label="付款时间">{{ fmtTime(detail.order.paid_at, true) }}</el-descriptions-item>
            <el-descriptions-item label="发货时间">{{ fmtTime(detail.order.delivered_at, true) }}</el-descriptions-item>
            <el-descriptions-item label="重试次数">{{ detail.order.retry_count }}</el-descriptions-item>
            <el-descriptions-item v-if="detail.order.fail_reason" label="失败原因"><span class="err">{{ detail.order.fail_reason }}</span></el-descriptions-item>
          </el-descriptions>

          <div class="ops mt">
            <el-button v-if="canDeliver(detail.order)" type="primary" :loading="busy[`d-${detail.order.id}`]" @click="deliver(detail.order)">手动发货</el-button>
            <el-button v-if="detail.order.status === 'risk_hold'" type="warning" plain @click="toManual(detail.order)">转人工</el-button>
          </div>

          <h4>发货记录</h4>
          <el-empty v-if="!detail.deliveries.length" description="暂无发货记录" :image-size="50" />
          <el-timeline v-else>
            <el-timeline-item
              v-for="d in detail.deliveries"
              :key="d.id"
              :timestamp="fmtTime(d.created_at, true)"
              :type="d.success ? 'success' : 'danger'"
            >
              <div class="rec-head">
                <el-tag size="small" :type="d.success ? 'success' : 'danger'">{{ d.success ? '成功' : '失败' }}</el-tag>
                <span class="small muted">{{ deliveryModeLabel[d.mode] || d.mode || '-' }}</span>
                <el-tag size="small" effect="plain" :type="d.message_sent ? 'success' : 'info'">消息{{ d.message_sent ? '已发' : '未发' }}</el-tag>
                <el-tag size="small" effect="plain" :type="d.consigned ? 'success' : 'info'">{{ d.consigned ? '已确认发货' : '未确认发货' }}</el-tag>
              </div>
              <div v-if="d.preview" class="preview">{{ d.preview }}</div>
              <div v-if="d.error" class="small err">{{ d.error }}</div>
            </el-timeline-item>
          </el-timeline>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.filters :deep(.el-card__body) {
  padding: 12px;
}
.w140 {
  width: 140px;
}
.w180 {
  width: 180px;
}
.w200 {
  width: 200px;
}
.price {
  color: #f56c6c;
  font-weight: 600;
}
.ml {
  margin-left: 4px;
}
.err {
  color: var(--el-color-danger);
}
.ops {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ops .el-button + .el-button {
  margin-left: 0;
}
.mt {
  margin-top: 12px;
}
h4 {
  margin: 20px 0 10px;
}
.rec-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.preview {
  margin-top: 6px;
  background: #f7f8fa;
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-all;
}
@media (max-width: 768px) {
  .w140,
  .w180,
  .w200 {
    width: calc(50% - 4px);
  }
}
</style>
