<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRealtimeStore } from '@/stores/realtime'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Search, WarningFilled } from '@element-plus/icons-vue'
import {
  closeHold,
  createBinding,
  deliverOrder,
  getOrder,
  importCards,
  listBindings,
  listOrders,
  listPools,
  resolveManualOrder,
  syncOrders,
  type DeliveryRecord,
  type Order,
  type PoolOut,
} from '@/api/order'
import BuyerRiskPanel from '@/components/BuyerRiskPanel.vue'
import StatusTag from '@/components/StatusTag.vue'
import ListPager from '@/components/ListPager.vue'
import { useAccountsStore } from '@/stores/accounts'
import { useMobile } from '@/composables/useMobile'
import { NEEDS_ACTION_STATUSES, fmtMoney, fmtTime, itemUrl, orderStatusMap } from '@/utils/format'

// 买家分析：发货前看看这个买家靠不靠谱
const buyerRisk = reactive({ open: false, order: null as Order | null })
function openBuyerRisk(o: Order) {
  Object.assign(buyerRisk, { open: true, order: o })
}

const route = useRoute()
const router = useRouter()
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

// ---------------------------------------------------------------- 就地快捷关联发货
const pools = ref<PoolOut[]>([])
const poolsLoaded = ref(false)

async function ensurePools() {
  if (poolsLoaded.value) return
  try {
    pools.value = await listPools()
    poolsLoaded.value = true
  } catch {
    /* 拦截器已处理 */
  }
}

const poolKindMap: Record<string, string> = {
  text: '固定内容 (网盘/说明)',
  pool: '卡密库存 (每单一条)',
  api: '接口取货 (第三方API)',
}

const quickBind = reactive({
  open: false,
  saving: false,
  delivering: false,
  order: null as Order | null,
  pool_id: null as number | null,
  applyToAll: true,
  template: '',
})

async function openQuickBind(o: Order) {
  await ensurePools()
  Object.assign(quickBind, {
    open: true,
    saving: false,
    delivering: false,
    order: o,
    pool_id: pools.value[0]?.id || null,
    applyToAll: true,
    template: '您好，订单已发货，内容如下：\n{content}\n如有问题请随时联系～',
  })
}

async function saveQuickBind(andDeliver = false) {
  if (!quickBind.order || !quickBind.pool_id) {
    ElMessage.warning('请选择要关联的发货内容')
    return
  }
  const o = quickBind.order
  if (!o.item_id) {
    ElMessage.error('该订单缺少闲鱼商品 ID，无法关联')
    return
  }
  quickBind.saving = true
  if (andDeliver) quickBind.delivering = true
  try {
    await createBinding({
      pool_id: quickBind.pool_id,
      account_id: quickBind.applyToAll ? null : o.account_id,
      item_id: o.item_id,
      spec_value: o.spec_value || null,
      template: quickBind.template.trim(),
      delay_seconds: 0,
      max_per_buyer: 0,
      auto_relist: false,
    })
    ElMessage.success('已关联发货内容')

    if (andDeliver) {
      const r = await deliverOrder(o.id)
      if (r.ok) {
        ElMessage.success('发货成功！内容已发出并已在闲鱼确认发货')
      } else {
        ElMessage.warning(`关联已保存，但发货提示：${r.error || r.status}`)
      }
    }
    quickBind.open = false
    await load(page.value)
    if (detail.open && detail.order?.id === o.id) await openDetail(o)
  } catch {
    /* 拦截器已处理 */
  } finally {
    quickBind.saving = false
    quickBind.delivering = false
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
  const targetId = filter.account_id || accounts.list[0]?.id
  if (!targetId) {
    ElMessage.warning('暂无可用的闲鱼账号')
    return
  }
  syncing.value = true
  try {
    const r = await syncOrders(targetId)
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
/** 因为商品没有关联发货内容而卡住的订单（与后端 NO_BINDING_REASON 对应） */
const needsLink = (o: Order) => canDeliver(o) && !!o.fail_reason?.includes('还没有关联发货内容')
/** 缺库存/缺卡密拦截的订单 */
const isOutOfStock = (o: Order) =>
  canDeliver(o) &&
  !!o.fail_reason &&
  (o.fail_reason.includes('库存') || o.fail_reason.includes('卡密不足') || o.fail_reason.includes('无可用卡密'))

// 缺库存就地快捷补卡并重试发货
const quickReplenish = reactive({
  open: false,
  saving: false,
  order: null as Order | null,
  pool_id: null as number | null,
  lines: '',
  autoDeliver: true,
})

async function openQuickReplenish(o: Order) {
  await ensurePools()
  const bindings = await listBindings().catch(() => [])
  const matched = bindings.find(
    (b) => b.item_id === o.item_id && (!b.account_id || b.account_id === o.account_id),
  )
  const poolId = matched?.pool_id || pools.value.find((p) => p.kind === 'pool')?.id || pools.value[0]?.id || null

  Object.assign(quickReplenish, {
    open: true,
    saving: false,
    order: o,
    pool_id: poolId,
    lines: '',
    autoDeliver: true,
  })
}

async function submitQuickReplenish() {
  if (!quickReplenish.order || !quickReplenish.pool_id) {
    ElMessage.warning('请选择要补充卡密的发货内容')
    return
  }
  const lines = quickReplenish.lines.trim()
  if (!lines) {
    ElMessage.warning('请输入要补充的卡密内容（一行一条）')
    return
  }
  const o = quickReplenish.order
  quickReplenish.saving = true
  try {
    const res = await importCards(quickReplenish.pool_id, lines)
    ElMessage.success(`成功补充 ${res.added} 条卡密${res.duplicated ? `（跳过 ${res.duplicated} 条重复）` : ''}`)

    if (quickReplenish.autoDeliver) {
      const r = await deliverOrder(o.id)
      if (r.ok) {
        ElMessage.success('发货成功！卡密已发出并已在闲鱼确认发货')
      } else {
        ElMessage.warning(`补卡成功，但发货提示：${r.error || r.status}`)
      }
    }
    quickReplenish.open = false
    await load(page.value)
    if (detail.open && detail.order?.id === o.id) await openDetail(o)
  } catch {
    /* 拦截器已提示 */
  } finally {
    quickReplenish.saving = false
  }
}

function goLink(o: Order) {
  router.push({ path: '/orders/cards', query: { tab: 'bindings', item_id: o.item_id || undefined } })
}

async function deliver(o: Order) {
  await ElMessageBox.confirm(
    `将立即为订单 ${o.order_id}（${o.buyer_nick || '买家'}，${fmtMoney(o.amount)}）发货：按商品关联的发货内容发给买家并在闲鱼确认发货。此操作跳过发货前风控检查。`,
    '手动发货',
    { type: 'warning', confirmButtonText: '确认发货' },
  )
  busy[`d-${o.id}`] = true
  try {
    const r = await deliverOrder(o.id)
    if (r.ok) {
      ElMessage.success('发货成功')
    } else if (r.code === 'no_binding') {
      ElMessage.warning('检测到该商品尚未关联发货内容，已为您打开就地关联弹窗')
      await openQuickBind(o)
    } else {
      ElMessage.error(`发货失败：${r.error || orderStatusMap[r.status]?.label || r.status}`)
    }
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

async function markResolved(o: Order) {
  await ElMessageBox.confirm(
    '确认该订单已在线下或闲鱼手机端完成发货 / 协商一致？标记后将转为「已发货」并解除待办报警。',
    '标记已处理',
    { type: 'success', confirmButtonText: '确定标记' },
  )
  busy[`m-${o.id}`] = true
  try {
    const r = await resolveManualOrder(o.id, 'delivered')
    ElMessage.success(`订单已标记处理完成，当前状态：${orderStatusMap[r.status]?.label || r.status}`)
    await load(page.value)
    if (detail.open && detail.order?.id === o.id) await openDetail(o)
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[`m-${o.id}`] = false
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
        <h2>订单管理</h2>
      </div>
      <div class="toolbar">
        <el-button :icon="Refresh" :loading="loading" round @click="load(page)">刷新列表</el-button>
      </div>
    </div>

    <el-card shadow="never" class="filters-card">
      <div class="toolbar">
        <el-select v-model="filter.account_id" clearable placeholder="全部闲鱼账号" class="w180" @change="load()">
          <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
        </el-select>
        <el-button type="primary" :icon="Refresh" :loading="syncing" :disabled="!filter.account_id" @click="sync">
          同步最新订单
        </el-button>
        <el-select v-model="filter.status" clearable placeholder="全部订单状态" class="w150" @change="load()">
          <el-option :value="NEEDS_ACTION_STATUSES" label="需要我处理（待发/风控/失败）" />
          <el-option v-for="(v, k) in orderStatusMap" :key="k" :value="k" :label="v.label" />
        </el-select>
        <el-input v-model="filter.q" placeholder="搜索订单号 / 商品 / 买家" clearable class="w220" :prefix-icon="Search" @keyup.enter="load()" @clear="load()" />
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <div class="table-wrap">
        <el-table v-loading="loading" :data="orders" @row-dblclick="(r: Order) => openDetail(r)">
          <template #empty>
            <div class="orders-empty-box">
              <el-empty description="暂无符合条件的订单记录">
                <el-button v-if="filter.account_id" :icon="Refresh" :loading="syncing" type="primary" @click="sync">
                  立即同步此账号订单
                </el-button>
              </el-empty>
            </div>
          </template>

          <el-table-column label="订单信息" min-width="210">
            <template #default="{ row }">
              <div class="order-id-row">
                <el-link type="primary" class="font-semibold mono" @click="openDetail(row as Order)">
                  {{ row.order_id }}
                </el-link>
              </div>
              <div class="muted smaller mt-xs">
                <span>{{ accounts.nameOf(row.account_id) }}</span>
                <span class="dot-sep">·</span>
                <span>{{ fmtTime(row.created_at) }}</span>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="交易商品" min-width="220">
            <template #default="{ row }">
              <div class="ellipsis font-semibold" :title="row.item_title">{{ row.item_title || row.item_id || '-' }}</div>
              <div v-if="row.spec_value" class="muted smaller">
                <el-tag size="small" type="info" effect="plain" class="mt-xs">
                  {{ row.spec_name || '规格' }}: {{ row.spec_value }}
                </el-tag>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="买家" min-width="120">
            <template #default="{ row }">
              <div class="buyer-cell">
                <div class="buyer-avatar">{{ (row.buyer_nick || row.buyer_id || '买')[0] }}</div>
                <div class="buyer-nick ellipsis">{{ row.buyer_nick || row.buyer_id || '-' }}</div>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="实付金额" width="130">
            <template #default="{ row }">
              <div class="price-wrap">
                <span class="price-val">{{ fmtMoney(row.amount) }}</span>
                <span v-if="row.quantity > 1" class="muted smaller"> ×{{ row.quantity }}</span>
              </div>
              <el-tag v-if="row.is_bargain" size="small" effect="plain" type="warning" class="mt-xs">
                议价成交
              </el-tag>
            </template>
          </el-table-column>

          <el-table-column label="订单状态" width="140">
            <template #default="{ row }">
              <StatusTag :value="row.status" :map="orderStatusMap" />
              <el-tooltip v-if="row.fail_reason" :content="row.fail_reason">
                <div class="smaller err ellipsis mt-xs fail-reason-row">
                  <el-icon><WarningFilled /></el-icon>
                  <span>{{ row.fail_reason }}</span>
                </div>
              </el-tooltip>
            </template>
          </el-table-column>

          <el-table-column label="付款 / 发货时间" width="160">
            <template #default="{ row }">
              <div class="smaller"><span class="muted">付:</span> {{ fmtTime(row.paid_at) || '-' }}</div>
              <div class="smaller mt-xs"><span class="muted">发:</span> {{ fmtTime(row.delivered_at) || '-' }}</div>
            </template>
          </el-table-column>

          <el-table-column label="操作" :width="isMobile ? 100 : 250" :fixed="isMobile ? undefined : 'right'">
            <template #default="{ row }">
              <div class="ops">
                <el-button size="small" @click="openDetail(row as Order)">详情</el-button>
                <el-button v-if="row.buyer_id" size="small" type="danger" plain @click="openBuyerRisk(row as Order)">买家</el-button>
                <el-button v-if="needsLink(row as Order)" size="small" type="warning" plain @click="openQuickBind(row as Order)">
                  关联发货
                </el-button>
                <el-button v-if="isOutOfStock(row as Order)" size="small" type="warning" plain @click="openQuickReplenish(row as Order)">
                  补卡发货
                </el-button>
                <el-button v-if="canDeliver(row as Order)" size="small" type="primary" :loading="busy[`d-${row.id}`]" @click="deliver(row as Order)">
                  {{ isOutOfStock(row as Order) ? '重试发货' : '手动发货' }}
                </el-button>
                <el-button v-if="row.status === 'risk_hold'" size="small" type="warning" plain :loading="busy[`h-${row.id}`]" @click="toManual(row as Order)">
                  转人工
                </el-button>
                <el-button
                  v-if="['manual', 'deliver_failed'].includes(row.status)"
                  size="small"
                  type="success"
                  plain
                  :loading="busy[`m-${row.id}`]"
                  @click="markResolved(row as Order)"
                >
                  标记已处理
                </el-button>
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
            <el-button v-if="needsLink(detail.order)" type="warning" plain @click="openQuickBind(detail.order)">关联发货</el-button>
            <el-button v-if="isOutOfStock(detail.order)" type="warning" plain @click="openQuickReplenish(detail.order)">一键补卡发货</el-button>
            <el-button v-if="canDeliver(detail.order)" type="primary" :loading="busy[`d-${detail.order.id}`]" @click="deliver(detail.order)">
              {{ isOutOfStock(detail.order) ? '重试发货' : '手动发货' }}
            </el-button>
            <el-button v-if="detail.order.status === 'risk_hold'" type="warning" plain @click="toManual(detail.order)">转人工</el-button>
            <el-button
              v-if="['manual', 'deliver_failed'].includes(detail.order.status)"
              type="success"
              plain
              :loading="busy[`m-${detail.order.id}`]"
              @click="markResolved(detail.order)"
            >
              标记已处理
            </el-button>
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

    <!-- 就地快捷关联发货弹窗 -->
    <el-dialog
      v-model="quickBind.open"
      title="快捷关联发货内容"
      width="540px"
      destroy-on-close
      class="quick-bind-dialog"
    >
      <div v-if="quickBind.order" class="quick-bind-body">
        <div class="quick-bind-summary">
          <div class="summary-line">
            <span class="muted">订单编号：</span>
            <span class="mono font-semibold">{{ quickBind.order.order_id }}</span>
            <span class="dot-sep">·</span>
            <span>{{ accounts.nameOf(quickBind.order.account_id) }}</span>
          </div>
          <div class="summary-line mt-xs">
            <span class="muted">商品标题：</span>
            <span class="font-semibold">{{ quickBind.order.item_title || quickBind.order.item_id }}</span>
          </div>
          <div v-if="quickBind.order.spec_value" class="summary-line mt-xs">
            <span class="muted">规格：</span>
            <el-tag size="small" effect="plain">{{ quickBind.order.spec_name }}：{{ quickBind.order.spec_value }}</el-tag>
          </div>
        </div>

        <el-alert
          type="info"
          :closable="false"
          show-icon
          class="mt"
          title="关联后，买家购买此商品将自动从此内容库取货发货；也可直接「保存并立即发货」，全程无需离开此界面。"
        />

        <el-form label-position="top" class="mt">
          <el-form-item label="选择发货内容库（固定网盘 / 卡密库存 / API）" required>
            <el-select v-model="quickBind.pool_id" placeholder="请选择发货内容" class="w-full">
              <el-option
                v-for="p in pools"
                :key="p.id"
                :value="p.id"
                :label="`${p.name} · ${poolKindMap[p.kind] || p.kind} ${p.kind === 'pool' ? `(余${p.stock?.available ?? 0})` : ''}`"
              />
            </el-select>
            <div v-if="!pools.length" class="smaller err mt-xs">
              暂无可用的发货内容，
              <el-link type="primary" class="smaller" @click="router.push('/orders/cards')">前往自动发货管理新建内容库 &gt;</el-link>
            </div>
          </el-form-item>

          <el-form-item label="生效范围">
            <el-radio-group v-model="quickBind.applyToAll">
              <el-radio :value="true">全部闲鱼账号通用（推荐）</el-radio>
              <el-radio :value="false">仅当前账号（{{ accounts.nameOf(quickBind.order.account_id) }}）有效</el-radio>
            </el-radio-group>
          </el-form-item>

          <el-collapse class="template-collapse">
            <el-collapse-item title="自定义发货消息模板（可选）" name="tpl">
              <el-input
                v-model="quickBind.template"
                type="textarea"
                :rows="3"
                placeholder="您好，订单已发货，内容如下：&#10;{content}&#10;如有问题请随时联系～"
              />
              <div class="muted smaller mt-xs">说明：{content} 会被自动替换为实际卡密或网盘说明。</div>
            </el-collapse-item>
          </el-collapse>
        </el-form>
      </div>

      <template #footer>
        <div class="bind-dialog-footer">
          <el-link type="info" class="smaller" @click="goLink(quickBind.order!)">前往「自动发货」页配置 &gt;</el-link>
          <div class="footer-btns">
            <el-button @click="quickBind.open = false">取消</el-button>
            <el-button :loading="quickBind.saving && !quickBind.delivering" @click="saveQuickBind(false)">
              仅保存关联
            </el-button>
            <el-button
              type="primary"
              :loading="quickBind.saving && quickBind.delivering"
              :disabled="!quickBind.pool_id"
              @click="saveQuickBind(true)"
            >
              保存并立即发货
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <!-- 缺库存就地快捷补卡弹窗 -->
    <el-dialog
      v-model="quickReplenish.open"
      title="一键补卡并重试发货"
      width="540px"
      destroy-on-close
      class="quick-replenish-dialog"
    >
      <div v-if="quickReplenish.order" class="quick-bind-body">
        <div class="quick-bind-summary">
          <div class="summary-line">
            <span class="muted">订单编号：</span>
            <span class="mono font-semibold">{{ quickReplenish.order.order_id }}</span>
            <span class="dot-sep">·</span>
            <span>{{ accounts.nameOf(quickReplenish.order.account_id) }}</span>
          </div>
          <div class="summary-line mt-xs">
            <span class="muted">商品标题：</span>
            <span class="font-semibold">{{ quickReplenish.order.item_title || quickReplenish.order.item_id }}</span>
          </div>
          <div v-if="quickReplenish.order.fail_reason" class="summary-line mt-xs">
            <span class="muted">拦截原因：</span>
            <span class="err">{{ quickReplenish.order.fail_reason }}</span>
          </div>
        </div>

        <el-alert
          type="warning"
          :closable="false"
          show-icon
          class="mt"
          title="直接在此粘贴新卡密即可就地导入库存，并自动重试发货，无需离开订单页面。"
        />

        <el-form label-position="top" class="mt">
          <el-form-item label="补充到" required>
            <el-select v-model="quickReplenish.pool_id" placeholder="请选择发货内容（卡密库存）" class="w-full">
              <el-option
                v-for="p in pools.filter((x) => x.kind === 'pool')"
                :key="p.id"
                :label="`${p.name}（当前可用库存: ${p.stock?.available ?? 0}）`"
                :value="p.id"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="补充卡密（一行一条）" required>
            <el-input
              v-model="quickReplenish.lines"
              type="textarea"
              :rows="5"
              placeholder="例如：&#10;CARD-AAAA-BBBB-CCCC&#10;CARD-DDDD-EEEE-FFFF"
            />
          </el-form-item>

          <el-form-item>
            <el-checkbox v-model="quickReplenish.autoDeliver">
              导入成功后立即自动为该订单发货（推荐）
            </el-checkbox>
          </el-form-item>
        </el-form>
      </div>

      <template #footer>
        <el-button @click="quickReplenish.open = false">取消</el-button>
        <el-button
          type="primary"
          :loading="quickReplenish.saving"
          @click="submitQuickReplenish"
        >
          确认补卡{{ quickReplenish.autoDeliver ? '并立即发货' : '' }}
        </el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="buyerRisk.open" :title="`买家分析 · ${buyerRisk.order?.buyer_nick || buyerRisk.order?.buyer_id || ''}`" size="520px" destroy-on-close>
      <BuyerRiskPanel v-if="buyerRisk.order" :order-pk="buyerRisk.order.id" />
    </el-drawer>
  </div>
</template>

<style scoped>
.filters-card :deep(.el-card__body) {
  padding: 14px 16px;
}
.filters-card {
  border-radius: 10px;
  border-color: var(--xh-border);
}
.table-card {
  border-radius: 10px;
  border-color: var(--xh-border);
}
.w150 {
  width: 150px;
}
.w180 {
  width: 180px;
}
.w220 {
  width: 220px;
}
.order-id-row {
  display: flex;
  align-items: center;
}
.dot-sep {
  margin: 0 4px;
}
.buyer-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.buyer-avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
  border: 1px solid var(--xh-primary-border);
  font-size: var(--xh-fs-xs);
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.buyer-nick {
  font-size: var(--xh-fs-sm);
  color: var(--xh-text);
}
.price-wrap {
  display: flex;
  align-items: baseline;
}
.price-val {
  color: var(--xh-price);
  font-weight: 700;
  font-size: var(--xh-fs-md);
  font-variant-numeric: tabular-nums;
}
.err {
  color: var(--xh-danger);
}
.fail-reason-row {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.orders-empty-box {
  padding: 40px 0;
  display: flex;
  justify-content: center;
}
.ops {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ops .el-button + .el-button {
  margin-left: 0;
}
.font-semibold {
  font-weight: 600;
}
.smaller {
  font-size: var(--xh-fs-xs);
}
.mt-xs {
  margin-top: 3px;
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
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, monospace;
  white-space: pre-wrap;
  word-break: break-all;
}
.quick-bind-summary {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 14px;
}
.summary-line {
  font-size: 13px;
  color: #1e293b;
}
.template-collapse {
  margin-top: 10px;
  border: none;
}
.template-collapse :deep(.el-collapse-item__header) {
  font-size: 12px;
  color: var(--xh-muted);
}
.bind-dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
.footer-btns {
  display: flex;
  gap: 8px;
}
.w-full {
  width: 100%;
}
@media (max-width: 768px) {
  .w150,
  .w180,
  .w220 {
    width: 100%;
  }
  .bind-dialog-footer {
    flex-direction: column-reverse;
    gap: 12px;
    align-items: flex-end;
  }
}
</style>
