<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DataLine, Delete, Key, MagicStick, MoreFilled, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { getMarket, listItems, offlineItem, polishAllItems, polishItem, syncItems, updateItem, type MarketView, type MyItem } from '@/api/goods'
import {
  createBinding,
  deleteBinding,
  listBindings,
  listPools,
  updateBinding,
  type BindingOut,
  type PoolOut,
} from '@/api/order'
import MarketPanel from '@/components/MarketPanel.vue'
import StatusTag from '@/components/StatusTag.vue'
import { useAccountsStore } from '@/stores/accounts'
import { useAuthStore } from '@/stores/auth'
import { useMobile } from '@/composables/useMobile'
import { fmtMoney, fmtRelative, fmtTime, goodsStatusMap, itemUrl, parseDate } from '@/utils/format'

const router = useRouter()
const accounts = useAccountsStore()
const auth = useAuthStore()
const isMobile = useMobile()
const items = ref<MyItem[]>([])
const loading = ref(false)
const syncing = ref(false)
const busy = reactive<Record<string, boolean>>({})
const route = useRoute()
const filter = reactive({
  account_id: (route.query.account_id ? Number(route.query.account_id) : undefined) as number | undefined,
  status: (typeof route.query.status === 'string' ? route.query.status : '') as string,
  q: '',
})

const selectedAccountExpired = computed(() => {
  if (!filter.account_id) return false
  const a = accounts.list.find((x) => x.id === filter.account_id)
  return a?.status === 'need_login'
})

watch(
  () => [route.query.status, route.query.account_id],
  ([newStatus, newAccId]) => {
    filter.status = typeof newStatus === 'string' ? newStatus : ''
    filter.account_id = newAccId ? Number(newAccId) : undefined
    load()
  },
)

async function load() {
  loading.value = true
  try {
    items.value = await listItems({
      account_id: filter.account_id,
      status: filter.status || undefined,
      q: filter.q.trim() || undefined,
    })
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  load()
  loadDelivery()
  await accounts.load().catch(() => undefined)
})

// ---------------------------------------------------------------- 自动发货关联
const bindings = ref<BindingOut[]>([])
const pools = ref<PoolOut[]>([])

async function loadDelivery() {
  try {
    ;[bindings.value, pools.value] = await Promise.all([listBindings(), listPools()])
  } catch {
    /* 仅用于展示，失败不影响商品列表 */
  }
}

const poolNameById = computed(() => new Map(pools.value.map((p) => [p.id, p.name])))
const bindingsByItem = computed(() => {
  const m = new Map<string, BindingOut[]>()
  for (const b of bindings.value) m.set(b.item_id, [...(m.get(b.item_id) || []), b])
  return m
})

/** 商品的自动发货状态；null 表示无法判断（非本人账号，关联属于账号所有者） */
function deliveryOf(it: MyItem): { names: string[] } | null {
  const acc = accounts.list.find((a) => a.id === it.account_id)
  if (acc && acc.owner_id !== auth.user?.id) return null
  const matched = (bindingsByItem.value.get(it.item_id) || []).filter(
    (b) => b.account_id === null || b.account_id === it.account_id,
  )
  return { names: [...new Set(matched.map((b) => poolNameById.value.get(b.pool_id) || `#${b.pool_id}`))] }
}

const poolKindMap: Record<string, string> = {
  text: '固定内容 (网盘/说明)',
  pool: '卡密库存 (每单一条)',
  api: '接口取货 (第三方API)',
}

const quickDelivery = reactive({
  open: false,
  saving: false,
  unbinding: false,
  item: null as MyItem | null,
  currentBinding: null as BindingOut | null,
  pool_id: null as number | null,
  applyToAll: true,
  template: '',
  autoRelist: false,
})

function openQuickDelivery(it: MyItem) {
  const matched = (bindingsByItem.value.get(it.item_id) || []).find(
    (b) => b.account_id === null || b.account_id === it.account_id,
  )
  Object.assign(quickDelivery, {
    open: true,
    saving: false,
    unbinding: false,
    item: it,
    currentBinding: matched || null,
    pool_id: matched?.pool_id ?? (pools.value[0]?.id || null),
    applyToAll: matched ? matched.account_id === null : true,
    autoRelist: matched?.auto_relist ?? false,
    template: matched?.template || '您好，订单已发货，内容如下：\n{content}\n如有问题请随时联系～',
  })
}

async function saveQuickDelivery() {
  if (!quickDelivery.item || !quickDelivery.pool_id) {
    ElMessage.warning('请选择要关联的发货内容')
    return
  }
  const it = quickDelivery.item
  quickDelivery.saving = true
  try {
    const body = {
      pool_id: quickDelivery.pool_id,
      account_id: quickDelivery.applyToAll ? null : it.account_id,
      item_id: it.item_id,
      spec_value: null,
      template: quickDelivery.template.trim(),
      // 更新时沿用原有的延迟 / 限购设置（这里没有对应输入项，不能重置为 0）
      delay_seconds: quickDelivery.currentBinding?.delay_seconds ?? 0,
      max_per_buyer: quickDelivery.currentBinding?.max_per_buyer ?? 0,
      auto_relist: quickDelivery.autoRelist,
    }
    if (quickDelivery.currentBinding) {
      await updateBinding(quickDelivery.currentBinding.id, body)
      ElMessage.success('已更新发货内容关联')
    } else {
      await createBinding(body)
      ElMessage.success('已关联发货内容')
    }
    quickDelivery.open = false
    await loadDelivery()
  } catch {
    /* 拦截器已提示 */
  } finally {
    quickDelivery.saving = false
  }
}

async function unbindQuickDelivery() {
  if (!quickDelivery.currentBinding) return
  await ElMessageBox.confirm('确定解除该商品的发货内容关联吗？解除后该商品付款将不再自动发货。', '解除关联', { type: 'warning' })
  quickDelivery.unbinding = true
  try {
    await deleteBinding(quickDelivery.currentBinding.id)
    ElMessage.success('已解除发货内容关联')
    quickDelivery.open = false
    await loadDelivery()
  } catch {
    /* 拦截器已提示 */
  } finally {
    quickDelivery.unbinding = false
  }
}

function goDeliveryCards(it?: MyItem | null) {
  router.push({ path: '/orders/cards', query: { tab: 'bindings', item_id: it?.item_id || undefined } })
}

async function sync() {
  if (!filter.account_id) {
    ElMessage.warning('请先选择要同步的账号')
    return
  }
  const acc = accounts.list.find((x) => x.id === filter.account_id)
  if (acc?.status === 'need_login') {
    ElMessageBox.confirm(
      `账号「${acc.remark || acc.nickname || acc.unb}」登录态已失效，无法同步商品。是否前往重新登录？`,
      '登录已失效',
      { confirmButtonText: '去重新登录', cancelButtonText: '取消', type: 'warning' },
    ).then(() => {
      router.push({ path: '/accounts', query: { relogin: String(filter.account_id) } })
    }).catch(() => {})
    return
  }
  syncing.value = true
  try {
    const r = await syncItems(filter.account_id)
    const summary = Object.entries(r)
      .map(([k, v]) => `${{ total: '共', created: '新增', updated: '更新', removed: '移除', stats: '补全数据' }[k] || k} ${v}`)
      .join('，')
    ElMessage.success(`同步完成：${summary || '无变化'}`)
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    syncing.value = false
  }
}

async function polish(it: MyItem) {
  busy[`p-${it.id}`] = true
  try {
    await polishItem(it.id)
    ElMessage.success('已擦亮')
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[`p-${it.id}`] = false
  }
}

const polishingAll = ref(false)
async function handlePolishAll() {
  await ElMessageBox.confirm(
    '将在后台按安全间隔依次擦亮在售商品，以提升曝光度并避免触发平台频率限制。确定立即执行？',
    '一键擦亮在售商品',
    { type: 'info', confirmButtonText: '开始擦亮' },
  )
  polishingAll.value = true
  try {
    const res = await polishAllItems(filter.account_id || undefined)
    ElMessage.success(res.message || '已在后台启动自动擦亮')
  } catch {
    /* 拦截器已处理 */
  } finally {
    polishingAll.value = false
  }
}

async function offline(it: MyItem) {
  await ElMessageBox.confirm(`将在闲鱼上下架「${it.title}」，确定？`, '下架商品', { type: 'warning' })
  busy[`o-${it.id}`] = true
  try {
    await offlineItem(it.id)
    ElMessage.success('已下架')
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[`o-${it.id}`] = false
  }
}

// ---------------------------------------------------------------- 议价策略 & 知识库
const edit = reactive({
  open: false,
  saving: false,
  item: null as MyItem | null,
  floor_price: null as number | null,
  max_rounds: 3,
  step_ratios: [] as number[],
  gifts: '',
  knowledge: '',
  desc: '',
  is_virtual: false,
})

function openEdit(it: MyItem) {
  Object.assign(edit, {
    open: true,
    item: it,
    floor_price: it.floor_price,
    max_rounds: it.max_rounds,
    step_ratios: [...(it.step_ratios?.length ? it.step_ratios : [0.4, 0.3, 0.2, 0.1])],
    gifts: it.gifts,
    knowledge: it.knowledge,
    desc: it.desc,
    is_virtual: it.is_virtual,
  })
}

const ratioSum = computed(() => edit.step_ratios.reduce((a, b) => a + (b || 0), 0))

/** 议价阶梯预览：每轮让出 (售价-底价) × 比例 */
const ladder = computed(() => {
  const price = edit.item?.price
  const floor = edit.floor_price
  if (!price || floor === null || floor === undefined || floor > price) return []
  const gap = price - floor
  let cur = price
  return edit.step_ratios.slice(0, edit.max_rounds).map((r, i) => {
    cur = Math.max(floor, cur - gap * (r || 0))
    return { round: i + 1, price: Math.round(cur * 100) / 100 }
  })
})

async function save() {
  const it = edit.item
  if (!it) return
  if (edit.floor_price !== null && it.price !== null && edit.floor_price > it.price) {
    ElMessage.warning('底价不能高于售价')
    return
  }
  if (ratioSum.value > 1.0001) {
    ElMessage.warning('让价比例合计不能超过 100%')
    return
  }
  edit.saving = true
  try {
    await updateItem(it.id, {
      floor_price: edit.floor_price,
      max_rounds: edit.max_rounds,
      step_ratios: edit.step_ratios.filter((x) => x > 0),
      gifts: edit.gifts,
      knowledge: edit.knowledge,
      desc: edit.desc,
      is_virtual: edit.is_virtual,
    })
    ElMessage.success('已保存')
    edit.open = false
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    edit.saving = false
  }
}

// ---------------------------------------------------------------- 行情
const market = reactive({ open: false, loading: false, item: null as MyItem | null, keyword: '', data: null as MarketView | null })

function openMarket(it: MyItem) {
  Object.assign(market, { open: true, item: it, keyword: it.title.slice(0, 30), data: null })
  queryMarket()
}

async function queryMarket() {
  if (!market.keyword.trim()) return
  market.loading = true
  try {
    market.data = await getMarket(market.keyword.trim(), market.item?.price)
  } catch {
    market.data = null
  } finally {
    market.loading = false
  }
}

// ---------------------------------------------------------------- 商品数据：想要 / 浏览 / 在架天数
function daysListed(row: MyItem) {
  if (!row.publish_time) return null
  const d = parseDate(row.publish_time)
  if (!d) return null
  return Math.max(0, Math.floor((Date.now() - d.getTime()) / 86_400_000))
}

/** 冷门 / 热门提示：只在数据足够时给出，不做无依据的判断 */
function listingHint(row: MyItem): { label: string; type: 'warning' | 'success'; tip: string } | null {
  const days = daysListed(row)
  if (row.status !== 'on_sale' || days === null || row.want_cnt == null) return null
  if (days >= 30 && row.want_cnt <= 2)
    return { label: '冷门', type: 'warning', tip: `已挂 ${days} 天只有 ${row.want_cnt} 人想要，可以考虑降价，或补充实拍图和描述后重新编辑` }
  if (days <= 7 && row.want_cnt >= 10)
    return { label: '热门', type: 'success', tip: `${days} 天内 ${row.want_cnt} 人想要，关注度高，可以坚持价格` }
  return null
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>商品管理</h2>
      </div>
      <div class="toolbar">
        <el-button type="primary" :icon="Plus" @click="router.push('/goods/publish')">发布新商品</el-button>
        <el-button :icon="Refresh" :loading="loading" round @click="load">刷新</el-button>
      </div>
    </div>

    <el-card shadow="never" class="filters">
      <div class="toolbar">
        <el-select v-model="filter.account_id" clearable placeholder="全部闲鱼账号" class="w180" @change="load">
          <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
        </el-select>
        <el-button type="primary" plain :icon="Refresh" :loading="syncing" :disabled="!filter.account_id" @click="sync">
          同步在售宝贝
        </el-button>
        <el-button :icon="MagicStick" :loading="polishingAll" @click="handlePolishAll">
          一键擦亮在售
        </el-button>
        <el-select v-model="filter.status" clearable placeholder="全部商品状态" class="w140" @change="load">
          <el-option v-for="(v, k) in goodsStatusMap" :key="k" :value="k" :label="v.label" />
        </el-select>
        <el-input v-model="filter.q" placeholder="搜索标题关键字" clearable class="w220" :prefix-icon="Search" @keyup.enter="load" @clear="load" />
      </div>
    </el-card>

    <el-alert
      v-if="selectedAccountExpired"
      type="warning"
      show-icon
      :closable="false"
      class="mb"
    >
      <template #title>
        <div style="display: flex; align-items: center; justify-content: space-between; width: 100%; gap: 12px;">
          <span>当前选中的闲鱼账号登录态已失效，无法同步商品或执行自动化擦亮。</span>
          <el-button
            type="primary"
            size="small"
            plain
            :icon="Key"
            @click="router.push({ path: '/accounts', query: { relogin: String(filter.account_id) } })"
          >
            去重新登录
          </el-button>
        </div>
      </template>
    </el-alert>

    <el-card shadow="never">
      <div class="table-wrap">
        <el-table v-loading="loading" :data="items">
          <template #empty>
            <div class="goods-empty-box">
              <el-empty description="暂无商品，选择账号后点击「同步在售宝贝」或新建发布">
                <div class="empty-btn-group">
                  <el-button v-if="filter.account_id" type="primary" :icon="Refresh" :loading="syncing" @click="sync">
                    同步账号商品
                  </el-button>
                  <el-button :icon="Plus" @click="router.push('/goods/publish')">发布新商品</el-button>
                </div>
              </el-empty>
            </div>
          </template>
          <el-table-column label="商品" min-width="280">
            <template #default="{ row }">
              <div class="goods">
                <el-image
                  :src="row.image_url"
                  fit="cover"
                  class="thumb"
                  lazy
                  referrerpolicy="no-referrer"
                  :preview-src-list="row.image_url ? [row.image_url] : []"
                  preview-teleported
                  hide-on-click-modal
                />
                <div class="goods-info">
                  <el-link :href="itemUrl(row.item_id)" target="_blank" class="goods-title">{{ row.title }}</el-link>
                  <div class="muted small">
                    {{ accounts.nameOf(row.account_id) }} · ID {{ row.item_id }}
                    <el-tag v-if="row.is_virtual" size="small" type="primary" effect="plain">虚拟</el-tag>
                  </div>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="售价" width="90">
            <template #default="{ row }"><span class="price">{{ fmtMoney(row.price) }}</span></template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }"><StatusTag :value="row.status" :map="goodsStatusMap" /></template>
          </el-table-column>
          <el-table-column label="数据" min-width="150">
            <template #default="{ row }">
              <div v-if="row.stats_at" class="stats">
                <span>想要 {{ row.want_cnt ?? '—' }} · 浏览 {{ row.browse_cnt ?? '—' }}</span>
                <span class="muted">在架 {{ daysListed(row as MyItem) ?? '—' }} 天</span>
                <el-tooltip v-if="listingHint(row as MyItem)" :content="listingHint(row as MyItem)!.tip">
                  <el-tag size="small" :type="listingHint(row as MyItem)!.type">{{ listingHint(row as MyItem)!.label }}</el-tag>
                </el-tooltip>
              </div>
              <span v-else class="muted small">-</span>
            </template>
          </el-table-column>
          <el-table-column label="议价底价" min-width="130">
            <template #default="{ row }">
              <template v-if="row.floor_price !== null">
                <div class="small font-medium">{{ fmtMoney(row.floor_price) }} ({{ row.max_rounds }}轮)</div>
                <div v-if="row.gifts" class="muted small ellipsis" :title="row.gifts">赠品: {{ row.gifts }}</div>
              </template>
              <span v-else class="muted small">未设底价</span>
            </template>
          </el-table-column>
          <el-table-column label="知识库" width="90">
            <template #default="{ row }">
              <el-tag v-if="row.knowledge" size="small" type="success" effect="plain">{{ row.knowledge.length }} 字</el-tag>
              <span v-else class="muted small">-</span>
            </template>
          </el-table-column>
          <el-table-column label="自动发货" min-width="130">
            <template #default="{ row }">
              <template v-if="deliveryOf(row as MyItem)">
                <el-tooltip v-if="deliveryOf(row as MyItem)!.names.length" content="点击修改发货内容" placement="top">
                  <el-tag size="small" type="success" effect="plain" class="clickable ellipsis-tag" @click="openQuickDelivery(row as MyItem)">
                    {{ deliveryOf(row as MyItem)!.names.join('、') }}
                  </el-tag>
                </el-tooltip>
                <el-button v-else-if="row.is_virtual" size="small" type="warning" plain @click="openQuickDelivery(row as MyItem)">去设置</el-button>
                <el-button v-else size="small" link type="primary" @click="openQuickDelivery(row as MyItem)">设置</el-button>
              </template>
              <span v-else class="muted small">-</span>
            </template>
          </el-table-column>
          <el-table-column label="同步 / 擦亮" width="140">
            <template #default="{ row }">
              <div class="small">{{ fmtRelative(row.synced_at) || '-' }}</div>
              <div class="muted small">擦亮 {{ fmtRelative(row.last_polished_at) || '-' }}</div>
            </template>
          </el-table-column>
          <el-table-column label="操作" :width="isMobile ? 110 : 166" :fixed="isMobile ? undefined : 'right'">
            <template #default="{ row }">
              <div class="compact-ops">
                <el-button size="small" type="primary" plain @click="openEdit(row as MyItem)">策略</el-button>
                <el-button
                  size="small"
                  :loading="busy[`p-${row.id}`]"
                  :disabled="row.status !== 'on_sale'"
                  @click="polish(row as MyItem)"
                >
                  擦亮
                </el-button>

                <el-dropdown trigger="click">
                  <el-button size="small" class="more-icon-btn" title="更多操作">
                    <el-icon><MoreFilled /></el-icon>
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item :icon="DataLine" @click="openMarket(row as MyItem)">
                        行情分析
                      </el-dropdown-item>
                      <el-dropdown-item
                        v-if="row.status === 'on_sale'"
                        :disabled="row.status !== 'on_sale'"
                        @click="offline(row as MyItem)"
                      >
                        <span class="err">下架宝贝</span>
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <!-- 策略编辑 -->
    <el-drawer v-model="edit.open" :title="edit.item?.title" size="560px">
      <el-form label-position="top" v-if="edit.item">
        <el-divider content-position="left">议价策略</el-divider>
        <el-form-item label="底价（元）">
          <el-input-number v-model="edit.floor_price" :min="0" :max="edit.item.price || undefined" :precision="2" :value-on-clear="null" placeholder="不设置" />
          <div class="form-tip">当前售价 {{ fmtMoney(edit.item.price) }}。AI 议价绝不低于底价；未设置底价时 AI 不会让价。</div>
        </el-form-item>
        <el-form-item label="最多议价轮数">
          <el-input-number v-model="edit.max_rounds" :min="0" :max="10" />
          <div class="form-tip">超过轮数后 AI 坚持当前价格，0 表示不议价。</div>
        </el-form-item>
        <el-form-item label="每轮让价比例">
          <div class="ratios">
            <div v-for="(_, i) in edit.step_ratios" :key="i" class="ratio">
              <span class="muted small">第 {{ i + 1 }} 轮</span>
              <el-input-number v-model="edit.step_ratios[i]" :min="0" :max="1" :step="0.05" :precision="2" size="small" />
              <el-button :icon="Delete" size="small" circle @click="edit.step_ratios.splice(i, 1)" />
            </div>
            <el-button size="small" :icon="Plus" :disabled="edit.step_ratios.length >= 10" @click="edit.step_ratios.push(0.1)">添加一轮</el-button>
          </div>
          <div class="form-tip">每轮让出（售价 − 底价）的比例，合计 {{ Math.round(ratioSum * 100) }}%（不超过 100%）。前期让得多、后期让得少更像真人。</div>
          <div v-if="ladder.length" class="ladder">
            <span class="small muted">报价预览：</span>
            <el-tag v-for="s in ladder" :key="s.round" size="small" effect="plain">第{{ s.round }}轮 {{ fmtMoney(s.price) }}</el-tag>
          </div>
        </el-form-item>
        <el-form-item label="赠品 / 让步筹码">
          <el-input v-model="edit.gifts" maxlength="128" placeholder="例如：送手机壳、包邮" />
          <div class="form-tip">买家坚持砍价但已到底价时，AI 可以用赠品代替降价。</div>
        </el-form-item>

        <el-divider content-position="left">客服知识</el-divider>
        <el-form-item label="知识库">
          <el-input v-model="edit.knowledge" type="textarea" :rows="8" maxlength="8000" show-word-limit placeholder="FAQ、参数、成色与瑕疵说明、使用教程、售后政策等。AI 回复只依据这里和商品描述，不会编造。" />
        </el-form-item>
        <el-form-item label="商品描述">
          <el-input v-model="edit.desc" type="textarea" :rows="4" placeholder="同步自闲鱼，可补充修改（仅本地，供 AI 参考）" />
        </el-form-item>
        <el-form-item label="虚拟商品">
          <el-switch v-model="edit.is_virtual" />
          <div class="form-tip">虚拟商品（卡密 / 账号 / 资料等）可在「订单发货 → 自动发货」中设置付款后自动发货。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="edit.open = false">取消</el-button>
        <el-button type="primary" :loading="edit.saving" @click="save">保存</el-button>
      </template>
    </el-drawer>

    <!-- 行情 -->
    <el-dialog v-model="market.open" title="查看行情" width="600px">
      <div class="mk-search">
        <el-input v-model="market.keyword" placeholder="搜索关键词（品牌 + 型号效果最好）" @keyup.enter="queryMarket" />
        <el-button type="primary" :loading="market.loading" @click="queryMarket">查询</el-button>
      </div>
      <div v-loading="market.loading" class="mk-body">
        <MarketPanel v-if="market.data" :data="market.data" :my-price="market.item?.price" />
        <el-empty v-else-if="!market.loading" description="查询失败或无数据" :image-size="50" />
      </div>
      <div class="form-tip">行情来自实时搜索（会消耗一次搜索频率）。最后同步：{{ fmtTime(market.item?.synced_at) }}</div>
    </el-dialog>

    <!-- 就地自动发货关联弹窗 -->
    <el-dialog
      v-model="quickDelivery.open"
      title="商品自动发货关联设置"
      width="540px"
      destroy-on-close
      class="quick-delivery-dialog"
    >
      <div v-if="quickDelivery.item" class="quick-delivery-body">
        <div class="quick-item-card">
          <el-image :src="quickDelivery.item.image_url" fit="cover" class="quick-thumb">
            <template #error>
              <div class="thumb-err">无图</div>
            </template>
          </el-image>
          <div class="quick-item-info">
            <div class="quick-item-title">{{ quickDelivery.item.title }}</div>
            <div class="quick-item-sub">
              <span class="price-val">{{ fmtMoney(quickDelivery.item.price) }}</span>
              <span class="dot-sep">·</span>
              <span class="muted small">{{ accounts.nameOf(quickDelivery.item.account_id) }}</span>
            </div>
          </div>
        </div>

        <el-alert
          type="info"
          :closable="false"
          show-icon
          class="mt"
          title="买家付款后，系统将自动从所选内容库取货（卡密库存自动去重扣减或发送网盘链接），并在闲鱼自动确认发货。"
        />

        <el-form label-position="top" class="mt">
          <el-form-item label="关联发货内容库（固定网盘 / 卡密库存 / API）" required>
            <el-select v-model="quickDelivery.pool_id" placeholder="请选择发货内容" class="w-full">
              <el-option
                v-for="p in pools"
                :key="p.id"
                :value="p.id"
                :label="`${p.name} · ${poolKindMap[p.kind] || p.kind} ${p.kind === 'pool' ? `(余${p.stock?.available ?? 0})` : ''}`"
              />
            </el-select>
            <div v-if="!pools.length" class="smaller err mt-xs">
              暂无可用的发货内容，
              <el-link type="primary" class="smaller" @click="goDeliveryCards()">前往自动发货管理新建内容库 &gt;</el-link>
            </div>
          </el-form-item>

          <el-form-item label="生效范围">
            <el-radio-group v-model="quickDelivery.applyToAll">
              <el-radio :value="true">全部闲鱼账号通用（推荐）</el-radio>
              <el-radio :value="false">仅当前账号（{{ accounts.nameOf(quickDelivery.item.account_id) }}）有效</el-radio>
            </el-radio-group>
          </el-form-item>

          <el-form-item label="卖完重新上架">
            <el-switch v-model="quickDelivery.autoRelist" />
            <div class="form-tip">
              闲鱼网页版只能发 1 件库存，卖出就下架。打开后，每次卖完会自动发布一件同样的新商品继续卖（卡密用完时不再上架）。
            </div>
          </el-form-item>

          <el-collapse class="template-collapse">
            <el-collapse-item title="自定义发货留言模板（可选）" name="tpl">
              <el-input
                v-model="quickDelivery.template"
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
          <div>
            <el-button
              v-if="quickDelivery.currentBinding"
              type="danger"
              plain
              size="small"
              :loading="quickDelivery.unbinding"
              @click="unbindQuickDelivery"
            >
              解除当前关联
            </el-button>
            <el-link type="info" class="smaller ml-xs" @click="goDeliveryCards(quickDelivery.item)">
              前往「自动发货」页 &gt;
            </el-link>
          </div>
          <div class="footer-btns">
            <el-button @click="quickDelivery.open = false">取消</el-button>
            <el-button
              type="primary"
              :loading="quickDelivery.saving"
              :disabled="!quickDelivery.pool_id"
              @click="saveQuickDelivery"
            >
              保存关联
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.filters :deep(.el-card__body) {
  padding: 12px 16px;
}
.filters .toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.clickable {
  cursor: pointer;
}
.ellipsis-tag {
  max-width: 100%;
}
.ellipsis-tag :deep(.el-tag__content) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.w120 {
  width: 120px;
}
.w180 {
  width: 180px;
}
.goods {
  display: flex;
  gap: 10px;
  align-items: center;
}
.thumb {
  width: 54px;
  height: 54px;
  border-radius: 6px;
  flex-shrink: 0;
  background: #f2f3f5;
}
.thumb-err {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  font-size: 12px;
  color: var(--xh-muted);
}
.goods-info {
  min-width: 0;
}
.goods-title {
  font-weight: 600;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.price {
  color: #f56c6c;
  font-weight: 600;
}
.compact-ops {
  display: flex;
  align-items: center;
  gap: 6px;
}
.compact-ops .el-button {
  border-radius: 6px;
  font-weight: 500;
}
.more-icon-btn {
  padding: 5px 8px !important;
  color: var(--xh-text-2);
}
.ops {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ops .el-button + .el-button {
  margin-left: 0;
}
.ratios {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-start;
}
.ratio {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ladder {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
  margin-top: 6px;
}
.mk-search {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.mk-body {
  min-height: 100px;
}
.goods-empty-box {
  padding: 40px 0;
  display: flex;
  justify-content: center;
}
.empty-btn-group {
  display: flex;
  gap: 12px;
  justify-content: center;
  margin-top: 12px;
}

/* 快捷关联发货弹窗样式 */
.quick-item-card {
  display: flex;
  gap: 12px;
  align-items: center;
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: 10px 12px;
}
.quick-thumb {
  width: 48px;
  height: 48px;
  border-radius: var(--xh-radius-sm);
  flex-shrink: 0;
  background: var(--xh-fill);
}
.quick-item-info {
  min-width: 0;
  flex: 1;
}
.quick-item-title {
  font-weight: 600;
  font-size: var(--xh-fs-sm);
  color: var(--xh-text);
  display: -webkit-box;
  -webkit-line-clamp: 1;
  line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.quick-item-sub {
  margin-top: 4px;
  display: flex;
  align-items: center;
}
.price-val {
  color: var(--xh-price);
  font-weight: 700;
  font-size: var(--xh-fs-md);
}
.dot-sep {
  margin: 0 6px;
  color: var(--xh-muted);
}
.template-collapse {
  margin-top: 10px;
  border: none;
}
.template-collapse :deep(.el-collapse-item__header) {
  font-size: var(--xh-fs-xs);
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
.ml-xs {
  margin-left: 6px;
}
.smaller {
  font-size: var(--xh-fs-xs);
}
.err {
  color: var(--xh-danger);
}
.mt-xs {
  margin-top: 4px;
}
.mt {
  margin-top: 12px;
}
@media (max-width: 768px) {
  .w120,
  .w180 {
    width: calc(50% - 4px);
  }
  .bind-dialog-footer {
    flex-direction: column-reverse;
    gap: 12px;
    align-items: flex-end;
  }
}
.stats {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px 6px;
  font-size: var(--xh-fs-xs);
}
</style>
