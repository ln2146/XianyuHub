<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Box, Connection, Document, Lightning, Plus, Refresh } from '@element-plus/icons-vue'
import {
  addBlacklist,
  createBinding,
  updateBinding,
  createPool,
  deleteBinding,
  deleteCard,
  deletePool,
  importCards,
  listBindings,
  listBlacklist,
  listCards,
  listPools,
  removeBlacklist,
  updatePool,
  type BindingIn,
  type BindingOut,
  type BlacklistEntry,
  type CardItem,
  type PoolIn,
  type PoolKind,
  type PoolOut,
} from '@/api/order'
import { listItems, type MyItem } from '@/api/goods'
import { updateAccount, type Account } from '@/api/account'
import { useAccountsStore } from '@/stores/accounts'
import { useMobile } from '@/composables/useMobile'
import { fmtTime } from '@/utils/format'
import ImageUploader from '@/components/ImageUploader.vue'

const accounts = useAccountsStore()
const isMobile = useMobile()
const route = useRoute()
const router = useRouter()
const tab = ref('pools')
const showGuide = ref(localStorage.getItem('xh_delivery_guide') === 'expanded')

function toggleGuide() {
  showGuide.value = !showGuide.value
  localStorage.setItem('xh_delivery_guide', showGuide.value ? 'expanded' : 'collapsed')
}

const kindMap: Record<PoolKind, { label: string; type: 'primary' | 'success' | 'warning'; tip: string }> = {
  text: { label: '固定内容', type: 'primary', tip: '每个买家收到的都一样，适合网盘链接、教程、资料等' },
  pool: { label: '卡密库存', type: 'success', tip: '每单发一条、发过不再发，适合激活码、兑换码、账号等；导入时自动去重' },
  api: { label: '接口取货', type: 'warning', tip: '买家付款后调用你自己的接口获取内容（适合有自有系统的卖家）' },
}

// ================================================================ 发货内容
const pools = ref<PoolOut[]>([])
const poolsLoading = ref(false)

async function loadPools() {
  poolsLoading.value = true
  try {
    pools.value = await listPools()
  } finally {
    poolsLoading.value = false
  }
}

const poolName = computed(() => {
  const m = new Map(pools.value.map((p) => [p.id, p.name]))
  return (id: number) => m.get(id) || `#${id}`
})

const API_EXAMPLE = `{
  "url": "https://example.com/api/card",
  "method": "POST",
  "headers": { "Authorization": "Bearer 你的密钥" },
  "body": { "order_id": "{order_id}", "spec": "{spec}", "quantity": "{quantity}" },
  "result_path": "data.card",
  "timeout": 15
}`

const poolEdit = reactive({
  open: false,
  saving: false,
  id: null as number | null,
  name: '',
  kind: 'pool' as PoolKind,
  text: '',
  apiJson: '',
  low_stock_threshold: 5,
  enabled: true,
  textPreview: null as string | null,
  images: [] as string[],
})
const poolImgUploading = ref(0)

function openPoolCreate() {
  Object.assign(poolEdit, {
    open: true,
    id: null,
    name: '',
    kind: 'pool',
    text: '',
    apiJson: API_EXAMPLE,
    low_stock_threshold: 5,
    enabled: true,
    textPreview: null,
    images: [],
  })
}

function openPoolEdit(p: PoolOut) {
  Object.assign(poolEdit, {
    open: true,
    id: p.id,
    name: p.name,
    kind: p.kind,
    text: '',
    apiJson: Object.keys(p.api_config || {}).length ? JSON.stringify(p.api_config, null, 2) : API_EXAMPLE,
    low_stock_threshold: p.low_stock_threshold,
    enabled: p.enabled,
    textPreview: p.text_preview,
    images: [...(p.images || [])],
  })
}

async function savePool() {
  if (!poolEdit.name.trim()) return ElMessage.warning('请填写名称')
  let api_config: Record<string, unknown> = {}
  if (poolEdit.kind === 'api') {
    try {
      const parsed: unknown = JSON.parse(poolEdit.apiJson || '{}')
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('需为 JSON 对象')
      api_config = parsed as Record<string, unknown>
    } catch (e) {
      return ElMessage.warning(`API 配置不是有效的 JSON：${(e as Error).message}`)
    }
    if (!/^https?:\/\//.test(String(api_config.url || ''))) return ElMessage.warning('API 配置需要有效的 url')
  }
  if (poolEdit.kind === 'text' && !poolEdit.id && !poolEdit.text.trim() && !poolEdit.images.length)
    return ElMessage.warning('请填写发货内容或添加图片')
  if (poolImgUploading.value) return ElMessage.warning('图片还在上传，请稍等')
  const body: PoolIn = {
    name: poolEdit.name.trim(),
    kind: poolEdit.kind,
    text: poolEdit.kind === 'text' && poolEdit.text.trim() ? poolEdit.text : null,
    api_config,
    images: poolEdit.images,
    low_stock_threshold: poolEdit.low_stock_threshold,
    enabled: poolEdit.enabled,
  }
  poolEdit.saving = true
  try {
    let createdId: number | null = null
    if (poolEdit.id) await updatePool(poolEdit.id, body)
    else createdId = (await createPool(body)).id
    ElMessage.success('已保存')
    poolEdit.open = false
    await loadPools()
    // 从订单 / 商品页跳转过来时：新建完内容接着关联那个商品
    if (createdId && pendingItemId.value) {
      const itemId = pendingItemId.value
      pendingItemId.value = null
      startLinkItem(itemId, createdId)
    }
  } catch {
    /* 拦截器已提示 */
  } finally {
    poolEdit.saving = false
  }
}

async function togglePool(p: PoolOut, enabled: boolean) {
  try {
    await updatePool(p.id, {
      name: p.name,
      kind: p.kind,
      text: null,
      api_config: {}, // 空对象表示不修改 API 配置
      low_stock_threshold: p.low_stock_threshold,
      enabled,
    })
    p.enabled = enabled
  } catch {
    /* 拦截器已提示 */
  }
}

async function removePool(p: PoolOut) {
  const linked = bindings.value.filter((b) => b.pool_id === p.id).length
  const tail = linked ? `${linked} 个商品的自动发货关联也会移除（商品本身不受影响），之后这些商品付款会转为人工发货。` : ''
  await ElMessageBox.confirm(`删除发货内容「${p.name}」？其中的卡密会一并删除，不可恢复。${tail}`, '删除发货内容', {
    type: 'error',
    confirmButtonText: '删除',
    confirmButtonClass: 'el-button--danger',
  })
  await deletePool(p.id)
  ElMessage.success('已删除')
  await Promise.all([loadPools(), loadBindings()])
}

// ---------------------------------------------------------------- 导入卡密
const imp = reactive({ open: false, saving: false, pool: null as PoolOut | null, lines: '' })
const importCount = computed(() => imp.lines.split('\n').filter((l) => l.trim()).length)

function openImport(p: PoolOut) {
  Object.assign(imp, { open: true, pool: p, lines: '' })
}

async function doImport() {
  if (!imp.pool || !importCount.value) return
  imp.saving = true
  try {
    const r = await importCards(imp.pool.id, imp.lines)
    ElMessage.success(`导入完成：新增 ${r.added} 条，重复跳过 ${r.duplicated} 条`)
    imp.open = false
    await loadPools()
  } catch {
    /* 拦截器已提示 */
  } finally {
    imp.saving = false
  }
}

// ---------------------------------------------------------------- 卡密列表
const cards = reactive({ open: false, loading: false, pool: null as PoolOut | null, status: '', list: [] as CardItem[] })
const cardStatus: Record<string, { label: string; type: 'success' | 'warning' | 'info' }> = {
  available: { label: '可用', type: 'success' },
  locked: { label: '已锁定', type: 'warning' },
  used: { label: '已使用', type: 'info' },
}

async function openCards(p: PoolOut) {
  Object.assign(cards, { open: true, pool: p, status: '', list: [] })
  await loadCards()
}

async function loadCards() {
  if (!cards.pool) return
  cards.loading = true
  try {
    cards.list = await listCards(cards.pool.id, cards.status)
  } finally {
    cards.loading = false
  }
}

async function removeCard(c: CardItem) {
  await ElMessageBox.confirm(`删除卡密 ${c.masked}？`, '删除卡密', { type: 'warning' })
  await deleteCard(c.id)
  ElMessage.success('已删除')
  await Promise.all([loadCards(), loadPools()])
}

// ================================================================ 商品关联
const bindings = ref<BindingOut[]>([])
const bindingsLoading = ref(false)
const goods = ref<MyItem[]>([])

async function loadBindings() {
  bindingsLoading.value = true
  try {
    bindings.value = await listBindings()
  } finally {
    bindingsLoading.value = false
  }
}

const goodsTitle = computed(() => {
  const m = new Map(goods.value.map((g) => [g.item_id, g.title]))
  return (id: string) => m.get(id) || ''
})

const TEMPLATE_VARS = [
  { key: '{content}', label: '发货内容（固定内容 / 卡密 / 接口返回）' },
  { key: '{order_id}', label: '订单号' },
  { key: '{buyer_name}', label: '买家昵称' },
  { key: '{item_title}', label: '商品标题' },
  { key: '{spec}', label: '规格' },
  { key: '{quantity}', label: '数量' },
]
const DEFAULT_TEMPLATE = '您好，订单已发货，内容如下：\n{content}\n如有问题请随时联系～'

const emptyBinding = (): BindingIn => ({
  pool_id: pools.value[0]?.id ?? 0,
  account_id: null,
  item_id: '',
  spec_value: null,
  template: DEFAULT_TEMPLATE,
  delay_seconds: 0,
  max_per_buyer: 0,
  auto_relist: false,
})

const bEdit = reactive({ open: false, saving: false, replaceId: null as number | null, form: emptyBinding() })
const templateRef = ref<{ textarea?: HTMLTextAreaElement }>()

function openBindingCreate() {
  if (!pools.value.length) {
    ElMessage.warning('请先在「① 发货内容」中新建要发给买家的内容')
    return
  }
  Object.assign(bEdit, { open: true, replaceId: null, form: emptyBinding() })
}

function openBindingEdit(b: BindingOut) {
  const { id: _id, ...rest } = b
  Object.assign(bEdit, { open: true, replaceId: b.id, form: { ...rest } })
}

function insertVar(v: string) {
  const ta = templateRef.value?.textarea
  const f = bEdit.form
  if (ta) {
    const start = ta.selectionStart ?? f.template.length
    const end = ta.selectionEnd ?? f.template.length
    f.template = f.template.slice(0, start) + v + f.template.slice(end)
  } else {
    f.template += v
  }
}

async function saveBinding() {
  const f = bEdit.form
  if (!f.pool_id) return ElMessage.warning('请选择发货内容')
  if (!f.item_id.trim()) return ElMessage.warning('请填写商品 ID')
  bEdit.saving = true
  try {
    const body = { ...f, item_id: f.item_id.trim(), spec_value: f.spec_value?.trim() || null }
    if (bEdit.replaceId) await updateBinding(bEdit.replaceId, body)
    else await createBinding(body)
    ElMessage.success('已保存')
    bEdit.open = false
    await loadBindings()
  } catch {
    /* 拦截器已提示 */
  } finally {
    bEdit.saving = false
  }
}

async function removeBinding(b: BindingOut) {
  await ElMessageBox.confirm(`取消商品 ${b.item_id} 的关联？取消后该商品付款后不再自动发货。`, '取消关联', { type: 'warning' })
  await deleteBinding(b.id)
  ElMessage.success('已删除')
  await loadBindings()
}

// ================================================================ 黑名单
const blacklist = ref<BlacklistEntry[]>([])
const blLoading = ref(false)
const blForm = reactive({ buyer_id: '', reason: '', saving: false })

async function loadBlacklist() {
  blLoading.value = true
  try {
    blacklist.value = await listBlacklist()
  } finally {
    blLoading.value = false
  }
}

async function addBl() {
  if (!blForm.buyer_id.trim()) return ElMessage.warning('请填写买家 ID')
  blForm.saving = true
  try {
    await addBlacklist(blForm.buyer_id.trim(), blForm.reason.trim())
    ElMessage.success('已加入黑名单')
    blForm.buyer_id = ''
    blForm.reason = ''
    await loadBlacklist()
  } catch {
    /* 拦截器已提示 */
  } finally {
    blForm.saving = false
  }
}

async function removeBl(e: BlacklistEntry) {
  await ElMessageBox.confirm(`将买家 ${e.buyer_id} 移出黑名单？`, '移出黑名单', { type: 'warning' })
  await removeBlacklist(e.id)
  ElMessage.success('已移出')
  await loadBlacklist()
}

function refreshAll() {
  return Promise.all([loadPools(), loadBindings(), loadBlacklist()])
}

// ================================================================ 从其他页面跳转来关联商品
/** 待关联的商品：还没有发货内容时先新建，保存后自动接着关联 */
const pendingItemId = ref<string | null>(null)

function startLinkItem(itemId: string, poolId?: number) {
  if (!pools.value.length) {
    pendingItemId.value = itemId
    tab.value = 'pools'
    ElMessage.info('先新建一份要发给买家的内容，保存后会自动带你去关联这个商品')
    openPoolCreate()
    return
  }
  tab.value = 'bindings'
  // 已有该商品的通用关联（不限规格、不限账号）则直接编辑，避免重复关联
  const existing = bindings.value.find((b) => b.item_id === itemId && !b.spec_value && !b.account_id)
  if (existing) {
    openBindingEdit(existing)
  } else {
    openBindingCreate()
    bEdit.form.item_id = itemId
  }
  if (poolId) bEdit.form.pool_id = poolId
}

onMounted(async () => {
  accounts.load().catch(() => undefined)
  listItems({})
    .then((r) => (goods.value = r))
    .catch(() => undefined)
  const { tab: qTab, item_id: qItem } = route.query
  if (typeof qTab === 'string' && ['pools', 'bindings', 'blacklist'].includes(qTab)) tab.value = qTab
  await refreshAll().catch(() => undefined)
  if (typeof qItem === 'string' && qItem) {
    startLinkItem(qItem)
    // 清掉参数，避免刷新页面时又弹出对话框
    router.replace({ path: route.path, query: { tab: tab.value } })
  }
})

watch(
  () => route.query.tab,
  (newTab) => {
    if (typeof newTab === 'string' && ['pools', 'bindings', 'blacklist'].includes(newTab)) {
      tab.value = newTab
    }
  },
)

const lowStock = (p: PoolOut) => p.kind === 'pool' && p.stock.available <= p.low_stock_threshold

// ================================================================ 账号发货免跳转管理
const accountsLoading = ref(false)
const accountToggling = reactive<Record<number, boolean>>({})

const accountDeliveryStats = computed(() => {
  const list = accounts.list
  if (!list.length) return { total: 0, enabled: 0, allEnabled: false }
  const enabled = list.filter((a) => a.settings?.auto_delivery).length
  return {
    total: list.length,
    enabled,
    allEnabled: enabled > 0 && enabled === list.length,
  }
})

async function toggleAccountDelivery(acc: Account, val: boolean) {
  accountToggling[acc.id] = true
  try {
    await updateAccount(acc.id, {
      settings: { ...acc.settings, auto_delivery: val },
    })
    if (acc.settings) acc.settings.auto_delivery = val
    ElMessage.success(`账号「${acc.remark || acc.nickname || acc.unb}」已${val ? '开启' : '关闭'}自动发货`)
    await accounts.load(true)
  } catch {
    /* 拦截器已处理 */
  } finally {
    accountToggling[acc.id] = false
  }
}

async function toggleAllAccountsDelivery(val: boolean) {
  accountsLoading.value = true
  try {
    for (const acc of accounts.list) {
      await updateAccount(acc.id, {
        settings: { ...acc.settings, auto_delivery: val },
      })
      if (acc.settings) acc.settings.auto_delivery = val
    }
    ElMessage.success(`已为全部 ${accounts.list.length} 个账号${val ? '开启' : '关闭'}自动发货`)
    await accounts.load(true)
  } finally {
    accountsLoading.value = false
  }
}

async function changeAccountDeliveryMode(acc: Account, mode: 'confirm_then_send' | 'send_then_confirm' | 'send_only') {
  try {
    await updateAccount(acc.id, {
      settings: { ...acc.settings, delivery_mode: mode },
    })
    if (acc.settings) acc.settings.delivery_mode = mode
    ElMessage.success('发货确认模式已更新')
    await accounts.load(true)
  } catch {
    /* 拦截器已处理 */
  }
}

const accountModal = reactive({
  open: false,
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>自动发货</h2>
      </div>
      <el-button :icon="Refresh" @click="refreshAll">刷新</el-button>
    </div>

    <!-- 自动发货极简 3 步向导卡片 -->
    <div class="delivery-steps-card" :class="{ 'is-collapsed': !showGuide }">
      <div class="steps-card-header">
        <div class="steps-title">
          <el-icon class="spark-icon"><Lightning /></el-icon>
          <span>自动发货 · 快速上手向导</span>
        </div>
        <el-button link size="small" class="guide-toggle-btn" @click="toggleGuide">
          {{ showGuide ? '收起向导' : '展开向导' }}
        </el-button>
      </div>

      <!-- 折叠态紧凑流程条 -->
      <div v-if="!showGuide" class="compact-guide-bar">
        <span class="muted smaller mr-xs">上手流程：</span>
        <div class="compact-guide-flow">
          <span class="compact-step" :class="{ ok: pools.length > 0 }" @click="tab = 'pools'">
            01 配置内容 ({{ pools.length }})
          </span>
          <span class="compact-sep">→</span>
          <span class="compact-step" :class="{ ok: bindings.length > 0 }" @click="tab = 'bindings'">
            02 绑定商品 ({{ bindings.length }})
          </span>
          <span class="compact-sep">→</span>
          <span
            class="compact-step"
            :class="{ ok: accountDeliveryStats.allEnabled, warn: accountDeliveryStats.enabled < accountDeliveryStats.total }"
            @click="accountModal.open = true"
          >
            03 开启发货 ({{ accountDeliveryStats.enabled }}/{{ accountDeliveryStats.total }})
          </span>
        </div>
      </div>

      <div v-else class="delivery-steps-grid">
        <div class="delivery-step-item" :class="{ current: tab === 'pools' }" @click="tab = 'pools'">
          <div class="step-num-badge">01</div>
          <div class="step-content">
            <div class="step-label">配置发货内容</div>
            <div class="step-detail">卡密库存 / 百度网盘 / 教程文档</div>
          </div>
          <el-button size="small" type="primary" plain class="step-action-btn" @click.stop="openPoolCreate">
            + 新建
          </el-button>
        </div>

        <div class="step-arrow-divider">→</div>

        <div class="delivery-step-item" :class="{ current: tab === 'bindings' }" @click="tab = 'bindings'">
          <div class="step-num-badge">02</div>
          <div class="step-content">
            <div class="step-label">绑定对应商品</div>
            <div class="step-detail">指定哪个商品发哪份内容与买家留言</div>
          </div>
          <el-button size="small" type="primary" plain class="step-action-btn" @click.stop="openBindingCreate">
            + 关联
          </el-button>
        </div>

        <div class="step-arrow-divider">→</div>

        <div
          class="delivery-step-item"
          :class="{ current: accountDeliveryStats.allEnabled, warning: !accountDeliveryStats.enabled }"
          @click="accountModal.open = true"
        >
          <div class="step-num-badge">03</div>
          <div class="step-content">
            <div class="step-label">
              <span>开启自动发货</span>
              <el-tag
                size="small"
                :type="accountDeliveryStats.allEnabled ? 'success' : accountDeliveryStats.enabled > 0 ? 'warning' : 'info'"
                effect="light"
                class="ml-s"
              >
                {{ accountDeliveryStats.enabled }}/{{ accountDeliveryStats.total }} 已开启
              </el-tag>
            </div>
            <div class="step-detail">
              {{ accountDeliveryStats.enabled > 0 ? '已接管发货，买家付款后系统自动发货' : '点击此处免跳转直接开启' }}
            </div>
          </div>

          <!-- 单账号直接放开关免跳转 -->
          <div v-if="accounts.list.length === 1" class="step-direct-switch" @click.stop>
            <el-switch
              :model-value="accounts.list[0].settings?.auto_delivery"
              :loading="accountToggling[accounts.list[0].id]"
              active-text="开"
              inactive-text="关"
              inline-prompt
              @change="(v: string | number | boolean) => toggleAccountDelivery(accounts.list[0], !!v)"
            />
          </div>
          <!-- 多账号提供一键开启与弹窗设置 -->
          <div v-else class="step-action-group" @click.stop>
            <el-button
              v-if="!accountDeliveryStats.allEnabled"
              size="small"
              type="success"
              plain
              :loading="accountsLoading"
              class="step-action-btn"
              @click="toggleAllAccountsDelivery(true)"
            >
              一键全开
            </el-button>
            <el-button size="small" class="step-action-btn" @click="accountModal.open = true">
              设置 &gt;
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <el-card shadow="never" class="content-card">
      <el-tabs v-model="tab" class="delivery-tabs">
        <!-- 发货内容 -->
        <el-tab-pane label="发货内容库" name="pools">
          <div class="tab-bar">
            <el-button type="primary" :icon="Plus" @click="openPoolCreate">新建发货内容</el-button>
          </div>
          <div class="table-wrap">
            <el-table v-loading="poolsLoading" :data="pools">
              <template #empty>
                <div class="tab-empty-box">
                  <el-empty description="还没有配置发货内容，点击下方按钮开始创建">
                    <el-button type="primary" :icon="Plus" @click="openPoolCreate">新建发货内容</el-button>
                  </el-empty>
                </div>
              </template>
              <el-table-column label="名称" prop="name" min-width="150">
                <template #default="{ row }">
                  <span class="font-semibold">{{ row.name }}</span>
                </template>
              </el-table-column>
              <el-table-column label="发货类型" width="120">
                <template #default="{ row }">
                  <el-tag size="small" :type="kindMap[row.kind as PoolKind]?.type" effect="light">
                    {{ kindMap[row.kind as PoolKind]?.label || row.kind }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="内容 / 剩余库存" min-width="240">
                <template #default="{ row }">
                  <template v-if="row.kind === 'pool'">
                    <div class="stock-cell">
                      <span class="stock-badge" :class="lowStock(row as PoolOut) ? 'low' : 'ok'">
                        可用 {{ row.stock.available }} 件
                      </span>
                      <span class="muted smaller">已锁定 {{ row.stock.locked }} · 已售出 {{ row.stock.used }}</span>
                      <el-tag v-if="lowStock(row as PoolOut)" size="small" type="danger" effect="dark" class="ml-s">
                        库存预警
                      </el-tag>
                    </div>
                  </template>
                  <span v-else-if="row.kind === 'text'" class="muted mono small ellipsis-text preview-inline" :title="row.text_preview">
                    <el-icon><Document /></el-icon> {{ row.text_preview || (row.images?.length ? '仅图片' : '已加密固定内容') }}
                  </span>
                  <span v-else class="muted mono small ellipsis-text preview-inline" :title="row.api_config?.url">
                    <el-icon><Connection /></el-icon> {{ row.api_config?.url || '自定义 API 接口' }}
                  </span>
                  <div v-if="row.images?.length" class="muted smaller">附 {{ row.images.length }} 张图片</div>
                </template>
              </el-table-column>
              <el-table-column label="库存预警阈值" width="120">
                <template #default="{ row }">
                  <span v-if="row.kind === 'pool'" class="small mono">≤ {{ row.low_stock_threshold }} 件</span>
                  <span v-else class="muted small">-</span>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-switch
                    :model-value="row.enabled"
                    size="small"
                    inline-prompt
                    active-text="启用"
                    inactive-text="关"
                    @change="(v: string | number | boolean) => togglePool(row as PoolOut, !!v)"
                  />
                </template>
              </el-table-column>
              <el-table-column label="操作" :width="isMobile ? 120 : 260" :fixed="isMobile ? undefined : 'right'">
                <template #default="{ row }">
                  <div class="ops">
                    <el-button v-if="row.kind === 'pool'" size="small" type="primary" plain @click="openImport(row as PoolOut)">
                      导入卡密
                    </el-button>
                    <el-button v-if="row.kind === 'pool'" size="small" @click="openCards(row as PoolOut)">
                      查看卡密
                    </el-button>
                    <el-button size="small" @click="openPoolEdit(row as PoolOut)">编辑</el-button>
                    <el-button size="small" type="danger" plain @click="removePool(row as PoolOut)">删除</el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <!-- 商品关联 -->
        <el-tab-pane label="商品关联规则" name="bindings">
          <div class="tab-bar">
            <el-button type="primary" :icon="Plus" @click="openBindingCreate">关联闲鱼商品</el-button>
          </div>
          <div class="table-wrap">
            <el-table v-loading="bindingsLoading" :data="bindings">
              <template #empty>
                <div class="tab-empty-box">
                  <el-empty description="还没有关联商品，指定哪个闲鱼商品付款后发哪份内容">
                    <el-button type="primary" :icon="Plus" @click="openBindingCreate">关联闲鱼商品</el-button>
                  </el-empty>
                </div>
              </template>
              <el-table-column label="对应闲鱼商品" min-width="220">
                <template #default="{ row }">
                  <div class="ellipsis font-semibold">{{ goodsTitle(row.item_id) || '商品' }}</div>
                  <div class="muted smaller mono">ID: {{ row.item_id }}</div>
                </template>
              </el-table-column>
              <el-table-column label="商品规格" width="120">
                <template #default="{ row }">
                  <el-tag size="small" effect="plain">{{ row.spec_value || '全部规格通用' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="发放内容库" min-width="140">
                <template #default="{ row }">
                  <span class="badge-pool-name"><el-icon><Box /></el-icon> {{ poolName(row.pool_id) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="限定账号" min-width="120">
                <template #default="{ row }">
                  <span class="small">{{ row.account_id ? accounts.nameOf(row.account_id) : '全部账号通用' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="给买家的留言模板" min-width="200" prop="template" show-overflow-tooltip>
                <template #default="{ row }">
                  <span class="muted small">{{ row.template || '使用默认留言（发货内容）' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="发货延迟" width="90">
                <template #default="{ row }">
                  <span class="small">{{ row.delay_seconds ? `${row.delay_seconds} 秒` : '即时发送' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="防刷限购" width="110">
                <template #default="{ row }">
                  <span class="small">{{ row.max_per_buyer ? `≤ ${row.max_per_buyer} 次/24h` : '不限' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="卖完重新上架" width="110">
                <template #default="{ row }">
                  <el-tag v-if="row.auto_relist" size="small" type="success" effect="plain">已开启</el-tag>
                  <span v-else class="muted small">关闭</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="130" :fixed="isMobile ? undefined : 'right'">
                <template #default="{ row }">
                  <el-button size="small" link type="primary" @click="openBindingEdit(row as BindingOut)">编辑</el-button>
                  <el-button size="small" link type="danger" @click="removeBinding(row as BindingOut)">解除关联</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <!-- 黑名单 -->
        <el-tab-pane label="买家黑名单" name="blacklist">
          <div class="muted small mb">黑名单中的买家下单后系统不会自动发货，订单自动转为人工处理。</div>
          <div class="toolbar mb">
            <el-input v-model="blForm.buyer_id" placeholder="买家 ID" class="w200" />
            <el-input v-model="blForm.reason" placeholder="原因备注（可选）" class="w240" />
            <el-button type="primary" :loading="blForm.saving" @click="addBl">加入黑名单</el-button>
          </div>
          <div class="table-wrap">
            <el-table v-loading="blLoading" :data="blacklist">
              <template #empty>
                <div class="tab-empty-box">
                  <el-empty description="当前黑名单为空，恶意跑单买家可在此加入拦截" />
                </div>
              </template>
              <el-table-column label="买家 ID" prop="buyer_id" min-width="160" />
              <el-table-column label="拦截原因" prop="reason" min-width="200">
                <template #default="{ row }">{{ row.reason || '-' }}</template>
              </el-table-column>
              <el-table-column label="加入时间" width="160">
                <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="90">
                <template #default="{ row }">
                  <el-button size="small" link type="danger" @click="removeBl(row as BlacklistEntry)">移出</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 发货内容编辑 -->
    <el-dialog v-model="poolEdit.open" :title="poolEdit.id ? '编辑发货内容' : '新建发货内容'" width="620px">
      <el-form label-width="100px" :label-position="isMobile ? 'top' : 'right'">
        <el-form-item label="名称" required>
          <el-input v-model="poolEdit.name" maxlength="64" placeholder="方便自己辨认，买家看不到，例如：PS 教程网盘" />
        </el-form-item>
        <el-form-item label="发货方式">
          <el-radio-group v-model="poolEdit.kind" :disabled="!!poolEdit.id">
            <el-radio-button v-for="(v, k) in kindMap" :key="k" :value="k">{{ v.label }}</el-radio-button>
          </el-radio-group>
          <div class="form-tip">{{ kindMap[poolEdit.kind].tip }}<template v-if="poolEdit.id">（类型创建后不可修改）</template></div>
        </el-form-item>
        <el-form-item v-if="poolEdit.kind === 'text'" label="发货内容" :required="!poolEdit.id">
          <el-input v-model="poolEdit.text" type="textarea" :rows="5" :placeholder="poolEdit.id ? `当前：${poolEdit.textPreview || ''}（留空表示不修改）` : '例如：网盘链接 https://… 提取码 xxxx'" />
        </el-form-item>
        <el-form-item v-if="poolEdit.kind === 'api'" label="API 配置" required>
          <el-input v-model="poolEdit.apiJson" type="textarea" :rows="11" class="mono" spellcheck="false" />
          <div class="form-tip">
            JSON 对象：url（必填）、method（GET / POST）、headers、body、result_path、timeout（秒）。
          </div>
        </el-form-item>
        <el-form-item label="附带图片">
          <ImageUploader
            v-model="poolEdit.images"
            v-model:uploading="poolImgUploading"
            :max="9"
            :pasteable="false"
            :allow-cover="false"
          />
          <div class="form-tip">发货文字之后按顺序发给买家，例如领取二维码、使用教程截图。固定内容可以只发图片。</div>
        </el-form-item>
        <el-form-item v-if="poolEdit.kind === 'pool'" label="库存预警">
          <el-input-number v-model="poolEdit.low_stock_threshold" :min="0" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="poolEdit.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="poolEdit.open = false">取消</el-button>
        <el-button type="primary" :loading="poolEdit.saving" @click="savePool">保存</el-button>
      </template>
    </el-dialog>

    <!-- 导入卡密 -->
    <el-dialog v-model="imp.open" :title="`导入卡密 · ${imp.pool?.name || ''}`" width="560px">
      <el-input v-model="imp.lines" type="textarea" :rows="12" class="mono" placeholder="每行一条卡密，例如：&#10;CARD-AAAA-1111&#10;CARD-BBBB-2222" spellcheck="false" />
      <div class="form-tip">共 {{ importCount }} 行；与已有卡密重复的会自动跳过。卡密加密存储。</div>
      <template #footer>
        <el-button @click="imp.open = false">取消</el-button>
        <el-button type="primary" :loading="imp.saving" :disabled="!importCount" @click="doImport">导入</el-button>
      </template>
    </el-dialog>

    <!-- 卡密列表 -->
    <el-dialog v-model="cards.open" :title="`卡密 · ${cards.pool?.name || ''}`" width="640px">
      <div class="toolbar mb">
        <el-radio-group v-model="cards.status" size="small" @change="loadCards">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="available">可用</el-radio-button>
          <el-radio-button value="locked">已锁定</el-radio-button>
          <el-radio-button value="used">已使用</el-radio-button>
        </el-radio-group>
        <span class="muted small">最多显示最近 500 条</span>
      </div>
      <div class="table-wrap">
        <el-table v-loading="cards.loading" :data="cards.list" size="small" max-height="420" empty-text="暂无卡密">
          <el-table-column label="卡密（脱敏）" min-width="160">
            <template #default="{ row }"><span class="mono">{{ row.masked }}</span></template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="cardStatus[row.status]?.type || 'info'">{{ cardStatus[row.status]?.label || row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="订单" width="80">
            <template #default="{ row }">{{ row.order_pk ? `#${row.order_pk}` : '-' }}</template>
          </el-table-column>
          <el-table-column label="使用时间" width="150">
            <template #default="{ row }">{{ fmtTime(row.used_at) }}</template>
          </el-table-column>
          <el-table-column label="" width="70">
            <template #default="{ row }">
              <el-button v-if="row.status === 'available'" size="small" link type="danger" @click="removeCard(row as CardItem)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>

    <!-- 绑定编辑 -->
    <el-dialog v-model="bEdit.open" :title="bEdit.replaceId ? '编辑商品关联' : '关联商品'" width="620px">
      <el-form label-width="100px" :label-position="isMobile ? 'top' : 'right'">
        <el-form-item label="发货内容" required>
          <el-select v-model="bEdit.form.pool_id" class="w240">
            <el-option v-for="p in pools" :key="p.id" :value="p.id" :label="`${p.name}（${kindMap[p.kind]?.label}）`" />
          </el-select>
        </el-form-item>
        <el-form-item label="商品" required>
          <el-select v-model="bEdit.form.item_id" filterable allow-create default-first-option placeholder="选择已同步的商品，或直接输入商品 ID" class="full">
            <el-option v-for="g in goods" :key="g.id" :value="g.item_id" :label="`${g.title}（${g.item_id}）`" />
          </el-select>
        </el-form-item>
        <el-form-item label="规格">
          <el-input v-model="bEdit.form.spec_value" placeholder="留空表示全部规格；多规格商品可按规格值分别关联不同内容" clearable />
        </el-form-item>
        <el-form-item label="限定账号">
          <el-select v-model="bEdit.form.account_id" clearable placeholder="全部账号" class="w240">
            <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
          </el-select>
        </el-form-item>
        <el-form-item label="发给买家的话">
          <el-input ref="templateRef" v-model="bEdit.form.template" type="textarea" :rows="5" placeholder="留空使用默认模板" />
          <div class="vars">
            <span class="muted small">插入变量：</span>
            <el-tooltip v-for="v in TEMPLATE_VARS" :key="v.key" :content="v.label">
              <el-tag size="small" class="var" effect="plain" @click="insertVar(v.key)">{{ v.key }}</el-tag>
            </el-tooltip>
          </div>
        </el-form-item>
        <el-form-item label="延迟发货">
          <el-input-number v-model="bEdit.form.delay_seconds" :min="0" :max="600" />
          <span class="muted small ml">秒</span>
        </el-form-item>
        <el-form-item label="每人限购">
          <el-input-number v-model="bEdit.form.max_per_buyer" :min="0" placeholder="0 表示不限" />
        </el-form-item>
        <el-form-item label="卖完重新上架">
          <el-switch v-model="bEdit.form.auto_relist" />
          <div class="form-tip">商品卖完下架后，自动发布一件同样的新商品，关联转到新商品上；卡密用完时不再上架。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bEdit.open = false">取消</el-button>
        <el-button type="primary" :loading="bEdit.saving" @click="saveBinding">保存</el-button>
      </template>
    </el-dialog>

    <!-- 账号自动发货免跳转设置弹窗 -->
    <el-dialog v-model="accountModal.open" title="账号自动发货开关管理" width="680px">
      <div class="account-modal-header">
        <div class="desc">在此快速管理每个闲鱼账号的自动发货开关与通知模式，修改即时生效，无需前往账号配置：</div>
        <div class="modal-quick-ops">
          <el-button size="small" type="success" plain :loading="accountsLoading" @click="toggleAllAccountsDelivery(true)">
            全部开启
          </el-button>
          <el-button size="small" plain :loading="accountsLoading" @click="toggleAllAccountsDelivery(false)">
            全部暂停
          </el-button>
        </div>
      </div>

      <div class="table-wrap mt-s">
        <el-table :data="accounts.list" size="small" empty-text="暂无绑定账号，请先添加账号">
          <el-table-column label="闲鱼账号" min-width="160">
            <template #default="{ row }">
              <div class="modal-acc-cell">
                <div class="modal-acc-avatar">{{ (row.remark || row.nickname || '闲')[0] }}</div>
                <div>
                  <div class="font-semibold">{{ row.remark || row.nickname || row.unb }}</div>
                  <div class="muted smaller mono">{{ row.nickname }}</div>
                </div>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="自动发货开关" width="130">
            <template #default="{ row }">
              <el-switch
                :model-value="row.settings?.auto_delivery"
                :loading="accountToggling[row.id]"
                active-text="开启"
                inactive-text="关闭"
                inline-prompt
                @change="(v: string | number | boolean) => toggleAccountDelivery(row as Account, !!v)"
              />
            </template>
          </el-table-column>

          <el-table-column label="发货通知模式" min-width="210">
            <template #default="{ row }">
              <el-select
                :model-value="row.settings?.delivery_mode || 'send_then_confirm'"
                size="small"
                class="full"
                @change="(v: 'confirm_then_send' | 'send_then_confirm' | 'send_only') => changeAccountDeliveryMode(row as Account, v)"
              >
                <el-option value="send_then_confirm" label="先发聊天消息，后点确认发货（推荐）" />
                <el-option value="confirm_then_send" label="先点确认发货，后发聊天消息" />
                <el-option value="send_only" label="仅发聊天消息，不点确认发货" />
              </el-select>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <template #footer>
        <div class="modal-footer-flex">
          <el-button link type="primary" size="small" @click="router.push('/accounts')">
            前往账号配置 &gt;
          </el-button>
          <el-button type="primary" @click="accountModal.open = false">完成</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.delivery-steps-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-lg);
  padding: var(--xh-space-4) var(--xh-space-5);
  box-shadow: var(--xh-shadow-1);
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
.delivery-steps-card.is-collapsed {
  padding: 12px 18px;
}
.delivery-steps-card.is-collapsed .steps-card-header {
  margin-bottom: 6px;
}
.compact-guide-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  flex-wrap: wrap;
}
.compact-guide-flow {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.compact-step {
  padding: 3px 8px;
  border-radius: 6px;
  background: var(--xh-fill);
  color: var(--xh-text-2);
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 12px;
}
.compact-step:hover {
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
}
.compact-step.ok {
  color: var(--xh-primary);
  font-weight: 600;
}
.compact-step.warn {
  color: var(--xh-warning);
}
.compact-sep {
  color: var(--xh-disabled);
  font-size: 11px;
}
.guide-toggle-btn {
  font-size: 12px;
  color: var(--xh-muted);
}
.guide-toggle-btn:hover {
  color: var(--xh-primary);
}
.steps-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--xh-space-3);
  flex-wrap: wrap;
  gap: var(--xh-space-2);
}
.steps-title {
  font-size: var(--xh-fs-md);
  font-weight: 700;
  color: var(--xh-text);
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
}
.spark-icon {
  font-size: var(--xh-fs-lg);
  color: var(--xh-primary);
}
.steps-desc {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}

.delivery-steps-grid {
  display: grid;
  grid-template-columns: 1fr auto 1fr auto 1fr;
  align-items: center;
  gap: var(--xh-space-3);
}
.delivery-step-item {
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: 12px 14px;
  display: flex;
  align-items: center;
  gap: var(--xh-space-3);
  cursor: pointer;
  transition: all 0.15s ease;
}
.delivery-step-item:hover {
  transform: translateY(-1px);
  border-color: var(--xh-primary-border);
  box-shadow: var(--xh-shadow-1);
}
.delivery-step-item.current {
  border-color: var(--xh-primary);
  background: var(--xh-primary-soft);
  box-shadow: 0 2px 8px rgba(30, 158, 106, 0.08);
}
.step-num-badge {
  width: 28px;
  height: 28px;
  border-radius: var(--xh-radius-sm);
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  color: var(--xh-text-2);
  font-weight: 700;
  font-size: var(--xh-fs-xs);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: ui-monospace, SFMono-Regular, monospace;
}
.delivery-step-item.current .step-num-badge {
  background: var(--xh-primary);
  border-color: var(--xh-primary);
  color: #ffffff;
}
.step-content {
  flex: 1;
  min-width: 0;
}
.step-label {
  font-size: var(--xh-fs-sm);
  font-weight: 600;
  color: var(--xh-text);
}
.step-detail {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.step-action-btn {
  font-size: var(--xh-fs-xs);
  padding: 4px 8px;
}
.step-arrow-divider {
  color: var(--xh-muted);
  font-size: var(--xh-fs-lg);
  font-weight: 600;
  user-select: none;
}

.content-card {
  border-radius: var(--xh-radius-lg);
  border-color: var(--xh-border);
}
.tab-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--xh-space-3);
  margin-bottom: 14px;
}
.tab-empty-box {
  padding: 36px 0;
  display: flex;
  justify-content: center;
}
.stock-cell {
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
  flex-wrap: wrap;
}
.stock-badge {
  padding: 2px 8px;
  border-radius: var(--xh-radius-sm);
  font-size: var(--xh-fs-xs);
  font-weight: 600;
  font-family: ui-monospace, SFMono-Regular, monospace;
}
.stock-badge.ok {
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
  border: 1px solid var(--xh-primary-border);
}
.stock-badge.low {
  background: var(--xh-danger-soft);
  color: var(--xh-danger);
  border: 1px solid var(--xh-danger-border);
}
.badge-pool-name {
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  padding: 2px 8px;
  border-radius: var(--xh-radius-sm);
  font-size: var(--xh-fs-xs);
  font-weight: 500;
  color: var(--xh-text-2);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.preview-inline {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.ellipsis-text {
  max-width: 320px;
  display: inline-block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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
.ml-s {
  margin-left: 6px;
}
.mb {
  margin-bottom: 12px;
}
.w200 {
  width: 200px;
}
.w240 {
  width: 240px;
  max-width: 100%;
}
.full {
  width: 100%;
}
.vars {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
  margin-top: 6px;
}
.var {
  cursor: pointer;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.mono :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: var(--xh-fs-xs);
}
.step-direct-switch {
  display: flex;
  align-items: center;
}
.step-action-group {
  display: flex;
  gap: 6px;
  align-items: center;
}
.delivery-step-item.warning {
  border-color: var(--xh-warning);
  background: var(--xh-warning-soft);
}
.account-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--xh-border);
}
.account-modal-header .desc {
  font-size: var(--xh-fs-sm);
  color: var(--xh-text-2);
  flex: 1;
}
.modal-quick-ops {
  display: flex;
  gap: 8px;
}
.modal-acc-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.modal-acc-avatar {
  width: 26px;
  height: 26px;
  border-radius: var(--xh-radius-sm);
  background: var(--xh-primary-soft);
  border: 1px solid var(--xh-primary-border);
  color: var(--xh-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--xh-fs-sm);
  font-weight: 600;
}
.modal-footer-flex {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}
@media (max-width: 900px) {
  .delivery-steps-grid {
    grid-template-columns: 1fr;
  }
  .step-arrow-divider {
    display: none;
  }
}
</style>
