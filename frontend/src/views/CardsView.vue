<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
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
import { useAccountsStore } from '@/stores/accounts'
import { useMobile } from '@/composables/useMobile'
import { fmtTime } from '@/utils/format'

const accounts = useAccountsStore()
const isMobile = useMobile()
const tab = ref('pools')

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
})

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
  if (poolEdit.kind === 'text' && !poolEdit.id && !poolEdit.text.trim()) return ElMessage.warning('请填写发货内容')
  const body: PoolIn = {
    name: poolEdit.name.trim(),
    kind: poolEdit.kind,
    text: poolEdit.kind === 'text' && poolEdit.text.trim() ? poolEdit.text : null,
    api_config,
    low_stock_threshold: poolEdit.low_stock_threshold,
    enabled: poolEdit.enabled,
  }
  poolEdit.saving = true
  try {
    if (poolEdit.id) await updatePool(poolEdit.id, body)
    else await createPool(body)
    ElMessage.success('已保存')
    poolEdit.open = false
    await loadPools()
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
  await ElMessageBox.confirm(`删除发货内容「${p.name}」？其中的卡密和关联的商品也会一并删除，此操作不可恢复。`, '删除发货内容', {
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
  loadPools()
  loadBindings()
  loadBlacklist()
}

onMounted(() => {
  refreshAll()
  accounts.load().catch(() => undefined)
  listItems({})
    .then((r) => (goods.value = r))
    .catch(() => undefined)
})

const lowStock = (p: PoolOut) => p.kind === 'pool' && p.stock.available <= p.low_stock_threshold
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>订单发货 · 自动发货</h2>
        <div class="sub">买家付款后，系统自动把你设置的内容发到聊天里，并在闲鱼上点「发货」</div>
      </div>
      <el-button :icon="Refresh" @click="refreshAll">刷新</el-button>
    </div>

    <el-alert type="info" :closable="false" class="steps-tip">
      <template #title>三步开启自动发货</template>
      <ol class="steps">
        <li><b>发货内容</b>：写好要发给买家的东西（网盘链接、卡密等）</li>
        <li><b>商品关联</b>：指定哪个商品发哪份内容</li>
        <li>到 <router-link to="/accounts">账号中心</router-link> → 设置，打开「自动发货」开关</li>
      </ol>
    </el-alert>

    <el-card shadow="never">
      <el-tabs v-model="tab">
        <!-- 发货内容 -->
        <el-tab-pane label="① 发货内容" name="pools">
          <div class="tab-bar">
            <el-button type="primary" :icon="Plus" @click="openPoolCreate">新建发货内容</el-button>
          </div>
          <div class="table-wrap">
            <el-table v-loading="poolsLoading" :data="pools" empty-text="还没有发货内容，点击「新建发货内容」开始">
              <el-table-column label="名称" prop="name" min-width="140" />
              <el-table-column label="类型" width="110">
                <template #default="{ row }">
                  <el-tag size="small" :type="kindMap[row.kind as PoolKind]?.type">{{ kindMap[row.kind as PoolKind]?.label || row.kind }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="内容 / 剩余库存" min-width="220">
                <template #default="{ row }">
                  <template v-if="row.kind === 'pool'">
                    <span :class="{ low: lowStock(row as PoolOut) }">可用 {{ row.stock.available }}</span>
                    <span class="muted small"> · 锁定 {{ row.stock.locked }} · 已用 {{ row.stock.used }}</span>
                    <el-tag v-if="lowStock(row as PoolOut)" size="small" type="danger" effect="plain" class="ml">库存不足</el-tag>
                  </template>
                  <span v-else-if="row.kind === 'text'" class="muted mono small">{{ row.text_preview || '-' }}</span>
                  <span v-else class="muted mono small ellipsis">{{ row.api_config.url || '-' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="库存预警" width="90">
                <template #default="{ row }">{{ row.kind === 'pool' ? `≤ ${row.low_stock_threshold}` : '-' }}</template>
              </el-table-column>
              <el-table-column label="启用" width="70">
                <template #default="{ row }">
                  <el-switch :model-value="row.enabled" size="small" @change="(v: string | number | boolean) => togglePool(row as PoolOut, !!v)" />
                </template>
              </el-table-column>
              <el-table-column label="操作" :width="isMobile ? 120 : 260" :fixed="isMobile ? undefined : 'right'">
                <template #default="{ row }">
                  <div class="ops">
                    <el-button v-if="row.kind === 'pool'" size="small" type="primary" plain @click="openImport(row as PoolOut)">导入卡密</el-button>
                    <el-button v-if="row.kind === 'pool'" size="small" @click="openCards(row as PoolOut)">查看卡密</el-button>
                    <el-button size="small" @click="openPoolEdit(row as PoolOut)">编辑</el-button>
                    <el-button size="small" type="danger" plain @click="removePool(row as PoolOut)">删除</el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <!-- 商品关联 -->
        <el-tab-pane label="② 商品关联" name="bindings">
          <div class="tab-bar">
            <el-button type="primary" :icon="Plus" @click="openBindingCreate">关联商品</el-button>
            <span class="muted small">只有关联了发货内容的商品，买家付款后才会自动发货</span>
          </div>
          <div class="table-wrap">
            <el-table v-loading="bindingsLoading" :data="bindings" empty-text="还没有关联商品，点击「关联商品」指定哪个商品发哪份内容">
              <el-table-column label="商品" min-width="200">
                <template #default="{ row }">
                  <div class="ellipsis">{{ goodsTitle(row.item_id) || '商品' }}</div>
                  <div class="muted small mono">{{ row.item_id }}</div>
                </template>
              </el-table-column>
              <el-table-column label="规格" width="110">
                <template #default="{ row }">{{ row.spec_value || '全部规格' }}</template>
              </el-table-column>
              <el-table-column label="发货内容" min-width="120">
                <template #default="{ row }">{{ poolName(row.pool_id) }}</template>
              </el-table-column>
              <el-table-column label="账号" min-width="110">
                <template #default="{ row }">{{ row.account_id ? accounts.nameOf(row.account_id) : '全部账号' }}</template>
              </el-table-column>
              <el-table-column label="发给买家的话" min-width="200" prop="template" show-overflow-tooltip />
              <el-table-column label="延迟" width="80">
                <template #default="{ row }">{{ row.delay_seconds ? `${row.delay_seconds} 秒` : '立即' }}</template>
              </el-table-column>
              <el-table-column label="每人限购/24h" width="110">
                <template #default="{ row }">{{ row.max_per_buyer || '不限' }}</template>
              </el-table-column>
              <el-table-column label="操作" width="130" :fixed="isMobile ? undefined : 'right'">
                <template #default="{ row }">
                  <el-button size="small" link type="primary" @click="openBindingEdit(row as BindingOut)">编辑</el-button>
                  <el-button size="small" link type="danger" @click="removeBinding(row as BindingOut)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <!-- 黑名单 -->
        <el-tab-pane label="买家黑名单" name="blacklist">
          <div class="muted small mb">黑名单中的买家下单后不会自动发货，订单转为人工处理。</div>
          <div class="toolbar mb">
            <el-input v-model="blForm.buyer_id" placeholder="买家 ID" class="w200" />
            <el-input v-model="blForm.reason" placeholder="原因（可选）" class="w240" />
            <el-button type="primary" :loading="blForm.saving" @click="addBl">加入黑名单</el-button>
          </div>
          <div class="table-wrap">
            <el-table v-loading="blLoading" :data="blacklist" empty-text="黑名单为空">
              <el-table-column label="买家 ID" prop="buyer_id" min-width="160" />
              <el-table-column label="原因" prop="reason" min-width="200">
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
          <div class="form-tip">内容加密存储，列表中只显示前 12 个字符。</div>
        </el-form-item>
        <el-form-item v-if="poolEdit.kind === 'api'" label="API 配置" required>
          <el-input v-model="poolEdit.apiJson" type="textarea" :rows="11" class="mono" spellcheck="false" />
          <div class="form-tip">
            JSON 对象：url（必填）、method（GET / POST）、headers、body（支持 {order_id} {spec} {quantity} 等变量）、result_path（从返回 JSON 中取值的路径，如 data.card；留空取整个响应文本）、timeout（秒）。
            <template v-if="poolEdit.id">headers 显示为 *** 时表示保持原值。</template>
          </div>
        </el-form-item>
        <el-form-item v-if="poolEdit.kind === 'pool'" label="说明">
          <span class="muted small">保存后在列表中点击「导入卡密」批量导入，每行一条。</span>
        </el-form-item>
        <el-form-item v-if="poolEdit.kind === 'pool'" label="库存预警">
          <el-input-number v-model="poolEdit.low_stock_threshold" :min="0" />
          <div class="form-tip">可用卡密低于该数量时发送「库存不足」通知。</div>
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
          <div class="form-tip">{content} 会被替换成上面选择的发货内容，其余变量按订单信息自动填充。</div>
        </el-form-item>
        <el-form-item label="延迟发货">
          <el-input-number v-model="bEdit.form.delay_seconds" :min="0" :max="600" />
          <span class="muted small ml">秒</span>
          <div class="form-tip">付款后等待一段时间再发货，更像人工操作。</div>
        </el-form-item>
        <el-form-item label="每人限购">
          <el-input-number v-model="bEdit.form.max_per_buyer" :min="0" />
          <div class="form-tip">同一买家 24 小时内最多自动发货的次数（跨账号统计），0 表示不限；超出后订单进入风控暂停，等待人工处理。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bEdit.open = false">取消</el-button>
        <el-button type="primary" :loading="bEdit.saving" @click="saveBinding">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.tab-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.steps-tip {
  margin-bottom: 12px;
}
.steps {
  margin: 4px 0 0;
  padding-left: 20px;
  line-height: 1.9;
}
.ops {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ops .el-button + .el-button {
  margin-left: 0;
}
.low {
  color: var(--el-color-danger);
  font-weight: 600;
}
.ml {
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
  font-size: 12px;
}
</style>
