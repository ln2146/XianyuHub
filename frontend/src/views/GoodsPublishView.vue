<script setup lang="ts">
/**
 * 发布商品：AI 优先。
 * 1. 上传图片（+ 一句话说明、定价策略）→ AI 生成整份草稿（标题、描述、价格、底价、运费、知识库）
 * 2. 确认页：逐项核对 AI 标出的待确认事项，按需修改 → 确认发布
 * 也可以切换为“手动填写”。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, EditPen, Loading, Location, MagicStick, Refresh, Warning } from '@element-plus/icons-vue'
import {
  aiDraft,
  createDraft,
  deleteDraft,
  getLocations,
  listDrafts,
  publishDraft,
  updateDraft,
  uploadUrl,
  type AiMeta,
  type DraftIn,
  type DraftOut,
  type ItemLocation,
  type PriceStrategy,
  type ShippingMode,
} from '@/api/goods'
import ImageUploader from '@/components/ImageUploader.vue'
import LocationPicker from '@/components/LocationPicker.vue'
import MarketPanel from '@/components/MarketPanel.vue'
import StatusTag from '@/components/StatusTag.vue'
import { useAccountsStore } from '@/stores/accounts'
import { useMobile } from '@/composables/useMobile'
import { draftStatusMap, fmtMoney, fmtTime, itemUrl } from '@/utils/format'
import { createBinding, listPools, type PoolOut } from '@/api/order'

const accounts = useAccountsStore()
const isMobile = useMobile()
const route = useRoute()

// ---------------------------------------------------------------- 状态
type Mode = 'ai' | 'review' | 'manual'
const mode = ref<Mode>('ai')

interface FormState {
  account_id: number | null
  title: string
  desc: string
  image_ids: string[]
  price: number | null
  orig_price: number | null
  quantity: number
  shipping: ShippingMode
  post_fee: number
  self_pickup: boolean
  floor_price: number | null
  knowledge: string
  is_virtual: boolean
  location: ItemLocation | null
  scheduled_at: Date | null
  delivery_pool_id: number | null
}

const emptyForm = (): FormState => ({
  account_id: accounts.list[0]?.id ?? null,
  title: '',
  desc: '',
  image_ids: [],
  price: null,
  orig_price: null,
  quantity: 1,
  shipping: 'free',
  post_fee: 0,
  self_pickup: false,
  floor_price: null,
  knowledge: '',
  is_virtual: false,
  location: null,
  scheduled_at: null,
  delivery_pool_id: null,
})

const form = reactive<FormState>(emptyForm())
const editingId = ref<number | null>(null)
const aiMeta = ref<AiMeta | null>(null)
const confirmed = reactive<Record<number, boolean>>({})
const saving = ref(false)
const publishing = ref(false)
const uploading = ref(0)
const pools = ref<PoolOut[]>([])

const gen = reactive({ hint: '', strategy: 'market' as PriceStrategy, loading: false, elapsed: 0 })
let timer: number | undefined

const strategyLabel: Record<PriceStrategy, string> = { quick: '快速出手', market: '市场价', premium: '高价试水' }
const strategyDesc: Record<PriceStrategy, string> = {
  quick: '比同款低价位再低一点，尽快成交',
  market: '参考同款成交中位价，稳妥',
  premium: '按同款偏高价位挂，适合不急卖',
}
const strategies = Object.keys(strategyLabel) as PriceStrategy[]

/** 一句话说明的快捷短语，点击追加 */
const hintChips = ['自用', '九成新', '无划痕', '无拆修', '配件齐全', '带原装充电器', '保修期内', '可小刀', '不议价']
function addHint(s: string) {
  if (gen.hint.includes(s)) return
  const cur = gen.hint.trim().replace(/[，,。\s]+$/, '')
  gen.hint = (cur ? `${cur}，${s}` : s).slice(0, 500)
}
const shippingLabel: Record<string, string> = {
  free: '包邮',
  by_distance: '按距离计费',
  fixed: '一口价运费',
  no_shipping: '无需邮寄',
}

function resetAll() {
  Object.assign(form, emptyForm())
  editingId.value = null
  aiMeta.value = null
  for (const k of Object.keys(confirmed)) delete confirmed[Number(k)]
  gen.hint = ''
  mode.value = 'ai'
}

/** 生成进度只是按耗时估算的阶段提示，不代表后端真实进度 */
const genStages = [
  { at: 0, label: '识别图片中的商品' },
  { at: 15, label: '撰写标题、描述和常见问题' },
  { at: 35, label: '查询同款行情、计算售价与底价' },
]
const genStageIndex = computed(() => genStages.filter((s) => gen.elapsed >= s.at).length - 1)

// ---------------------------------------------------------------- 步骤条
const steps = ['上传图片', 'AI 生成', '核对确认', '发布']
const stepActive = computed(() => {
  if (mode.value === 'review') return 2
  if (gen.loading) return 1
  return form.image_ids.length ? 1 : 0
})

function fillFromDraft(d: DraftOut) {
  Object.assign(form, {
    account_id: d.account_id,
    title: d.title,
    desc: d.desc,
    image_ids: [...d.image_ids],
    price: d.price > 0 ? d.price : null,
    orig_price: d.orig_price,
    quantity: d.quantity,
    shipping: d.shipping,
    post_fee: d.post_fee,
    self_pickup: d.self_pickup,
    floor_price: d.floor_price,
    knowledge: d.knowledge,
    is_virtual: d.is_virtual,
    location: d.location,
    scheduled_at: d.scheduled_at ? new Date(d.scheduled_at) : null,
  })
  editingId.value = d.id
  aiMeta.value = d.ai_meta
  for (const k of Object.keys(confirmed)) delete confirmed[Number(k)]
  if (d.ai_meta) {
    gen.hint = d.ai_meta.hint || ''
    gen.strategy = d.ai_meta.strategy || 'market'
  }
}

async function generate(regenerate = false) {
  if (!form.account_id) return ElMessage.warning('请选择发布账号')
  if (!form.image_ids.length) return ElMessage.warning('请先上传至少一张商品图片')
  if (regenerate) {
    await ElMessageBox.confirm('重新生成会覆盖当前草稿里的标题、描述、价格和知识库，确定继续？', '重新生成', {
      type: 'warning',
    })
  }
  gen.loading = true
  gen.elapsed = 0
  timer = window.setInterval(() => (gen.elapsed += 1), 1000)
  try {
    const d = await aiDraft({
      account_id: form.account_id,
      image_ids: form.image_ids,
      hint: gen.hint.trim(),
      strategy: gen.strategy,
      draft_id: regenerate ? editingId.value : null,
    })
    fillFromDraft(d)
    mode.value = 'review'
    ElMessage.success(`已生成，用时 ${gen.elapsed} 秒。请核对后发布`)
    await loadDrafts()
    scrollTop()
  } catch {
    /* 拦截器已提示 */
  } finally {
    window.clearInterval(timer)
    gen.loading = false
  }
}

// ---------------------------------------------------------------- 确认页辅助
const uncertain = computed(() => aiMeta.value?.uncertain ?? [])
const unconfirmedCount = computed(() => uncertain.value.filter((_, i) => !confirmed[i]).length)
const suggestion = computed(() => aiMeta.value?.market?.suggestion ?? null)

function pickPrice(p: number) {
  form.price = p
  if (form.floor_price !== null && form.floor_price > p) form.floor_price = Math.floor(p * 0.9)
  ElMessage.success(`售价已设为 ${fmtMoney(p)}`)
}

function applyStrategy(s: PriceStrategy) {
  const sug = suggestion.value
  if (!sug) return
  gen.strategy = s
  pickPrice({ quick: sug.quick_sale, market: sug.market, premium: sug.premium }[s])
}

// ---------------------------------------------------------------- 保存 / 发布
function toBody(): DraftIn | null {
  if (!form.account_id) return ElMessage.warning('请选择发布账号'), null
  if (!form.image_ids.length) return ElMessage.warning('请至少上传一张图片'), null
  if (!form.title.trim()) return ElMessage.warning('请填写标题'), null
  if (!form.desc.trim()) return ElMessage.warning('请填写描述'), null
  if (!form.price || form.price <= 0) return ElMessage.warning('请填写售价'), null
  if (form.floor_price !== null && form.floor_price > form.price) return ElMessage.warning('底价不能高于售价'), null
  return {
    account_id: form.account_id,
    title: form.title.trim(),
    desc: form.desc.trim(),
    image_ids: form.image_ids,
    price: form.price,
    orig_price: form.orig_price,
    quantity: form.quantity,
    shipping: form.shipping,
    post_fee: form.shipping === 'fixed' ? form.post_fee : 0,
    self_pickup: form.self_pickup,
    floor_price: form.floor_price,
    knowledge: form.knowledge,
    is_virtual: form.is_virtual,
    location: form.location,
    scheduled_at: form.scheduled_at ? form.scheduled_at.toISOString() : null,
  }
}

// ---------------------------------------------------------------- 宝贝所在地
// 草稿未单独选择时，发布沿用该账号上次使用的所在地
const savedLocation = ref<ItemLocation | null>(null)
const locationOpen = ref(false)
const effectiveLocation = computed(() => form.location || savedLocation.value)
const locationText = (l: ItemLocation) => `${l.city}${l.area ? ` ${l.area}` : ''} · ${l.poi || l.address}`
watch(
  () => form.account_id,
  async (id) => {
    savedLocation.value = null
    if (!id) return
    try {
      savedLocation.value = (await getLocations(id)).saved
    } catch {
      /* 拦截器已提示 */
    }
  },
  { immediate: true },
)
function needLocation(): boolean {
  if (effectiveLocation.value) return false
  ElMessage.warning('请先选择宝贝所在地')
  locationOpen.value = true
  return true
}

async function persist(body: DraftIn): Promise<DraftOut> {
  const d = editingId.value ? await updateDraft(editingId.value, body) : await createDraft(body)
  editingId.value = d.id
  return d
}

async function saveDraft() {
  const body = toBody()
  if (!body) return
  saving.value = true
  try {
    await persist(body)
    ElMessage.success(body.scheduled_at ? '已保存为定时发布' : '草稿已保存')
    resetAll()
    await loadDrafts()
  } catch {
    /* 拦截器已提示 */
  } finally {
    saving.value = false
  }
}

function publishConfirmText(title: string, price: number, accountId: number, pending: number) {
  const lines = [
    `将以账号「${accounts.nameOf(accountId)}」在闲鱼上发布「${title}」，售价 ${fmtMoney(price)}。`,
    '发布受频率保护（默认每个账号 5 分钟 1 个），发布后可在闲鱼 App 中修改或下架。',
  ]
  if (pending) lines.unshift(`注意：还有 ${pending} 项 AI 标注的信息未确认。`)
  return lines.join('\n')
}

/** 确认页：保存修改后立即发布 */
async function confirmAndPublish() {
  const body = toBody()
  if (!body) return
  if (needLocation()) return
  if (body.scheduled_at) return saveDraft()
  await ElMessageBox.confirm(
    publishConfirmText(body.title, body.price, body.account_id, unconfirmedCount.value),
    '确认发布到闲鱼',
    { type: 'warning', confirmButtonText: '确认发布' },
  )
  publishing.value = true
  try {
    const d = await persist(body)
    const r = await publishDraft(d.id)
    ElMessage.success(`发布成功，商品 ID ${r.item_id}`)
    if (form.delivery_pool_id && r.item_id) {
      try {
        await createBinding({
          pool_id: form.delivery_pool_id,
          account_id: body.account_id,
          item_id: r.item_id,
          spec_value: null,
          template: '您购买的内容如下：\n{card}\n祝您使用愉快！',
          delay_seconds: 0,
          max_per_buyer: 1,
        })
        ElMessage.success('已自动关联发货内容库')
      } catch {
        /* 仅辅助绑定，失败可在商品管理中补绑 */
      }
    }
    resetAll()
  } catch {
    /* 拦截器已提示；草稿已保存，可稍后在右侧列表重试 */
  } finally {
    publishing.value = false
    await loadDrafts()
  }
}

// ---------------------------------------------------------------- 草稿列表
const drafts = ref<DraftOut[]>([])
const draftsLoading = ref(false)
const busy = reactive<Record<string, boolean>>({})

async function loadDrafts() {
  draftsLoading.value = true
  try {
    drafts.value = await listDrafts()
  } finally {
    draftsLoading.value = false
  }
}

function scrollTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
  document.querySelector('.main')?.scrollTo({ top: 0, behavior: 'smooth' })
}

function openDraft(d: DraftOut) {
  fillFromDraft(d)
  mode.value = d.ai_meta ? 'review' : 'manual'
  scrollTop()
}

async function publishFromList(d: DraftOut) {
  if (!d.price || d.price <= 0) {
    openDraft(d)
    return ElMessage.warning('该草稿还没有售价，请先补全')
  }
  await ElMessageBox.confirm(publishConfirmText(d.title, d.price, d.account_id, 0), '立即发布到闲鱼', {
    type: 'warning',
    confirmButtonText: '确认发布',
  })
  busy[`pub-${d.id}`] = true
  try {
    const r = await publishDraft(d.id)
    ElMessage.success(`发布成功，商品 ID ${r.item_id}`)
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[`pub-${d.id}`] = false
    await loadDrafts()
  }
}

async function removeDraft(d: DraftOut) {
  await ElMessageBox.confirm(`删除草稿「${d.title || '未命名'}」？`, '删除草稿', { type: 'warning' })
  await deleteDraft(d.id)
  if (editingId.value === d.id) resetAll()
  ElMessage.success('已删除')
  await loadDrafts()
}

const canEdit = (d: DraftOut) => d.status !== 'published' && d.status !== 'publishing'
const titleLen = computed(() => form.title.length)

type DraftFilter = 'all' | 'pending' | 'published'
const draftFilter = ref<DraftFilter>('all')
const isPublished = (d: DraftOut) => d.status === 'published'
const filteredDrafts = computed(() => {
  if (draftFilter.value === 'all') return drafts.value
  return drafts.value.filter((d) => (draftFilter.value === 'published' ? isPublished(d) : !isPublished(d)))
})
const draftFilterOptions = computed(() => {
  const pub = drafts.value.filter(isPublished).length
  return [
    { value: 'all', label: `全部 ${drafts.value.length}` },
    { value: 'pending', label: `未发布 ${drafts.value.length - pub}` },
    { value: 'published', label: `已发布 ${pub}` },
  ]
})

onMounted(async () => {
  loadDrafts()
  listPools().then((p) => { pools.value = p }).catch(() => undefined)
  await accounts.load().catch(() => undefined)
  if (!form.account_id) form.account_id = accounts.list[0]?.id ?? null

  const q = route.query
  if (q.from === 'resell') {
    if (typeof q.title === 'string' && q.title.trim()) {
      form.title = q.title.trim().slice(0, 60)
    }
    if (q.price) {
      form.price = Number(q.price)
    }
    if (typeof q.hint === 'string' && q.hint.trim()) {
      gen.hint = q.hint.trim()
    }
    ElMessage.success('已自动带入雷达好货信息，补充实拍商品图后即可一键 AI 生成！')
  }
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="page publish-page">
    <div class="page-head">
      <div>
        <h2>发布商品</h2>
        <ol v-if="mode !== 'manual'" class="stepper">
          <li v-for="(s, i) in steps" :key="s" :class="{ done: i < stepActive, active: i === stepActive }">
            <span class="dot">
              <el-icon v-if="i < stepActive"><Check /></el-icon>
              <template v-else>{{ i + 1 }}</template>
            </span>
            <span class="label">{{ s }}</span>
          </li>
        </ol>
      </div>
      <div>
        <el-button v-if="mode !== 'ai'" :icon="MagicStick" @click="resetAll">新的 AI 发布</el-button>
        <el-button v-if="mode === 'ai'" :icon="EditPen" link type="primary" @click="mode = 'manual'">不用 AI，手动填写</el-button>
      </div>
    </div>

    <el-row :gutter="12" class="publish-row">
      <el-col :xs="24" :lg="14" class="publish-left-col">
        <!-- 第一步：上传图片，AI 生成 -->
        <el-card v-if="mode === 'ai'" shadow="never" class="ai-card publish-card">
          <template #header>
            <div class="card-head">
              <div>
                <div class="card-title"><span class="ai-badge"><el-icon><MagicStick /></el-icon></span> AI 生成商品信息</div>
              </div>
            </div>
          </template>
          <el-form label-width="90px" :label-position="isMobile ? 'top' : 'right'" class="publish-form">
            <el-form-item label="发布账号" required>
              <el-select v-model="form.account_id" placeholder="选择账号" class="w240">
                <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
              </el-select>
            </el-form-item>
            <el-form-item label="商品图片" required>
              <ImageUploader v-model="form.image_ids" v-model:uploading="uploading" :allow-cover="false" />
            </el-form-item>
            <el-form-item label="一句话说明">
              <el-input
                v-model="gen.hint"
                type="textarea"
                :autosize="{ minRows: 2, maxRows: 5 }"
                maxlength="500"
                show-word-limit
                placeholder="可选。例如：自用一年，屏幕无划痕，带原装充电器，1500 出，最低 1300"
              />
              <div class="chips">
                <button
                  v-for="c in hintChips"
                  :key="c"
                  type="button"
                  class="chip"
                  :class="{ on: gen.hint.includes(c) }"
                  @click="addHint(c)"
                >
                  {{ gen.hint.includes(c) ? '✓ ' : '+ ' }}{{ c }}
                </button>
              </div>
            </el-form-item>
            <el-form-item label="定价策略">
              <div class="strategy-cards" role="radiogroup">
                <button
                  v-for="k in strategies"
                  :key="k"
                  type="button"
                  role="radio"
                  :aria-checked="gen.strategy === k"
                  class="s-card"
                  :class="{ on: gen.strategy === k }"
                  @click="gen.strategy = k"
                >
                  <span class="s-title">{{ strategyLabel[k] }}</span>
                  <span class="s-desc">{{ strategyDesc[k] }}</span>
                </button>
              </div>
            </el-form-item>
          </el-form>

          <div class="gen-footer">
            <div v-if="gen.loading" class="gen-progress">
              <div
                v-for="(s, i) in genStages"
                :key="s.label"
                class="g-step"
                :class="{ done: i < genStageIndex, active: i === genStageIndex }"
              >
                <el-icon v-if="i < genStageIndex"><Check /></el-icon>
                <el-icon v-else-if="i === genStageIndex" class="is-loading"><Loading /></el-icon>
                <span v-else class="g-dot" />
                {{ s.label }}
              </div>
              <div v-if="gen.elapsed >= 60" class="form-tip">快好了，部分模型需要 1~2 分钟，请稍候…</div>
            </div>
            <div v-else class="gen-note">
              {{ form.image_ids.length ? `已选 ${form.image_ids.length} 张图片，通常 30~60 秒完成，生成后可逐项核对` : '先上传至少一张商品图片' }}
            </div>
            <div class="gen-btn-group">
              <el-button v-if="form.image_ids.length || gen.hint" size="large" :disabled="gen.loading" @click="resetAll">
                清空重置
              </el-button>
              <el-button
                type="primary"
                size="large"
                class="gen-btn"
                :icon="MagicStick"
                :loading="gen.loading"
                :disabled="!form.image_ids.length || uploading > 0"
                @click="generate(false)"
              >
                {{ gen.loading ? `生成中 ${gen.elapsed}s` : uploading > 0 ? '图片上传中…' : 'AI 生成商品信息' }}
              </el-button>
            </div>
          </div>
        </el-card>

        <!-- 第二步：确认页（AI 草稿）/ 手动填写 -->
        <el-card v-else shadow="never" class="review-card publish-card">
          <template #header>
            <div class="card-head">
              <span>
                {{ mode === 'review' ? '核对 AI 生成的商品信息' : editingId ? `编辑草稿 #${editingId}` : '手动填写' }}
                <el-tag v-if="aiMeta" size="small" type="success" effect="plain" class="ml">AI 生成 · {{ aiMeta.model }}</el-tag>
              </span>
              <el-button v-if="aiMeta" size="small" :icon="Refresh" :loading="gen.loading" @click="generate(true)">
                {{ gen.loading ? `重新生成中 ${gen.elapsed}s` : '重新生成' }}
              </el-button>
            </div>
          </template>

          <template v-if="aiMeta">
            <el-alert v-for="w in aiMeta.warnings" :key="w" :title="w" type="warning" :closable="false" show-icon class="mb" />
            <div v-if="uncertain.length" class="confirm-box">
              <div class="confirm-head">
                <el-icon><Warning /></el-icon>
                请确认以下 AI 无法从图片判断的信息（已确认 {{ uncertain.length - unconfirmedCount }}/{{ uncertain.length }}）
              </div>
              <el-checkbox v-for="(u, i) in uncertain" :key="i" v-model="confirmed[i]" class="confirm-item">{{ u }}</el-checkbox>
            </div>
            <div class="ai-tags">
              <el-tag size="small" type="success">{{ aiMeta.condition }}</el-tag>
              <el-tag v-if="aiMeta.brand_model" size="small" effect="plain">{{ aiMeta.brand_model }}</el-tag>
              <el-tag v-for="h in aiMeta.highlights" :key="h" size="small" effect="plain">{{ h }}</el-tag>
              <el-tag v-for="f in aiMeta.flaws" :key="f" size="small" type="warning" effect="plain">瑕疵：{{ f }}</el-tag>
            </div>
          </template>

          <el-form label-width="90px" :label-position="isMobile ? 'top' : 'right'" class="publish-form">
            <el-form-item label="发布账号" required>
              <el-select v-model="form.account_id" placeholder="选择账号" class="w240">
                <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
              </el-select>
            </el-form-item>
            <el-form-item label="图片" required>
              <ImageUploader v-model="form.image_ids" v-model:uploading="uploading" />
              <div v-if="aiMeta?.cover_changed" class="form-tip">AI 已把最适合的图片设为首图。</div>
            </el-form-item>

            <el-form-item label="标题" required>
              <el-input v-model="form.title" maxlength="60" show-word-limit placeholder="品牌型号 + 核心卖点" />
              <div v-if="aiMeta && aiMeta.titles.length > 1" class="alt-titles">
                <span class="muted small">候选：</span>
                <el-tag
                  v-for="t in aiMeta.titles"
                  :key="t"
                  size="small"
                  :type="form.title === t ? 'primary' : 'info'"
                  :effect="form.title === t ? 'dark' : 'plain'"
                  class="alt"
                  @click="form.title = t.slice(0, 60)"
                >{{ t }}</el-tag>
              </div>
              <div v-if="titleLen > 30" class="form-tip">标题建议 30 字以内，过长在列表中会被截断。</div>
            </el-form-item>
            <el-form-item label="描述" required>
              <el-input v-model="form.desc" type="textarea" :rows="6" maxlength="5000" show-word-limit placeholder="入手渠道 / 时间、成色与瑕疵、配件、出售原因、交易方式。不要留站外联系方式。" />
            </el-form-item>

            <el-form-item label="价格" required>
              <div class="range">
                <el-input-number v-model="form.price" :min="0.01" :precision="2" :controls="false" placeholder="售价" :value-on-clear="null" />
                <span class="muted">原价</span>
                <el-input-number v-model="form.orig_price" :min="0" :precision="2" :controls="false" placeholder="可选" :value-on-clear="null" />
                <span class="muted">数量</span>
                <el-input-number v-model="form.quantity" :min="1" />
              </div>
              <div v-if="aiMeta" class="form-tip">定价依据：{{ aiMeta.price_source }}</div>
              <div v-if="suggestion" class="strategy">
                <span class="muted small">按行情改价：</span>
                <el-button v-for="(label, k) in strategyLabel" :key="k" size="small" :type="gen.strategy === k ? 'primary' : 'default'" plain @click="applyStrategy(k)">
                  {{ label }} {{ fmtMoney({ quick: suggestion.quick_sale, market: suggestion.market, premium: suggestion.premium }[k]) }}
                </el-button>
              </div>
            </el-form-item>
            <el-form-item label="底价">
              <el-input-number v-model="form.floor_price" :min="0" :precision="2" :controls="false" placeholder="不设置" :value-on-clear="null" />
            </el-form-item>
            <el-form-item label="运费">
              <el-radio-group v-model="form.shipping">
                <el-radio-button v-for="(label, k) in shippingLabel" :key="k" :value="k">{{ label }}</el-radio-button>
              </el-radio-group>
              <div v-if="form.shipping === 'fixed'" class="range mt-s">
                <span class="muted">运费</span>
                <el-input-number v-model="form.post_fee" :min="0" :precision="2" />
                <span class="muted">元</span>
              </div>
              <div v-if="aiMeta?.shipping_reason" class="form-tip">AI 建议：{{ aiMeta.shipping_reason }}</div>
              <el-checkbox v-model="form.self_pickup" class="mt-s">支持自提</el-checkbox>
            </el-form-item>
            <el-form-item label="宝贝所在地" required>
              <div class="location-field">
                <template v-if="effectiveLocation">
                  <el-icon class="muted"><Location /></el-icon>
                  <span class="ellipsis">{{ locationText(effectiveLocation) }}</span>
                  <span v-if="!form.location" class="muted small">（沿用上次）</span>
                </template>
                <span v-else class="muted">未选择</span>
                <el-button link type="primary" @click="locationOpen = true">{{ effectiveLocation ? '更换' : '选择' }}</el-button>
              </div>
            </el-form-item>
            <el-form-item label="客服知识库">
              <el-input v-model="form.knowledge" type="textarea" :rows="aiMeta ? 8 : 3" placeholder="可选：FAQ、参数、瑕疵说明等，发布后供 AI 客服回答买家" />
            </el-form-item>
            <el-form-item label="虚拟商品">
              <el-switch v-model="form.is_virtual" />
            </el-form-item>
            <el-form-item label="自动发货">
              <el-select
                v-model="form.delivery_pool_id"
                clearable
                placeholder="买家付款后自动发货内容（可选，如网盘资料/激活码）"
                class="w360"
              >
                <el-option
                  v-for="p in pools"
                  :key="p.id"
                  :value="p.id"
                  :label="`${p.name} · ${p.kind === 'text' ? '固定文案/网盘' : p.kind === 'pool' ? '卡密库存' : '接口取货'}`"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="定时发布">
              <el-date-picker v-model="form.scheduled_at" type="datetime" placeholder="留空表示立即发布" :disabled-date="(d: Date) => d.getTime() < Date.now() - 86400000" />
            </el-form-item>

            <el-collapse v-if="aiMeta?.market" class="mb">
              <el-collapse-item :title="`同款行情（关键词「${aiMeta.market.keyword}」，${aiMeta.market.sample} 个样本）`">
                <MarketPanel :data="aiMeta.market" :my-price="form.price" @pick="pickPrice" />
              </el-collapse-item>
            </el-collapse>

            <el-form-item class="publish-form-actions">
              <el-button type="primary" :loading="publishing" :disabled="gen.loading" @click="confirmAndPublish">
                {{ form.scheduled_at ? '确认并定时发布' : '确认并发布' }}
              </el-button>
              <el-button :loading="saving" :disabled="gen.loading" @click="saveDraft">保存草稿</el-button>
              <el-button :disabled="publishing || saving" @click="resetAll">清空重置</el-button>
              <el-button v-if="mode === 'manual' && !editingId" link type="primary" @click="mode = 'ai'">改用 AI 生成</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="10" class="publish-right-col">
        <div class="publish-sidebar-wrap">
          <!-- 草稿与发布记录卡片 -->
          <el-card shadow="never" class="drafts">
            <template #header>
              <div class="card-head">
                <span class="card-title">草稿与发布记录</span>
                <el-button :icon="Refresh" link :loading="draftsLoading" @click="loadDrafts">刷新</el-button>
              </div>
              <el-segmented
                v-if="drafts.length"
                v-model="draftFilter"
                :options="draftFilterOptions"
                size="small"
                block
                class="d-filter"
              />
            </template>
            <el-empty
              v-if="!draftsLoading && !filteredDrafts.length"
              :description="drafts.length ? '该分类下暂无记录' : '还没有草稿，AI 生成后会自动保存到这里'"
              :image-size="60"
            />
            <div v-loading="draftsLoading" class="draft-list">
              <div v-for="d in filteredDrafts" :key="d.id" class="draft" :class="{ editing: editingId === d.id }">
                <el-image :src="d.image_ids[0] ? uploadUrl(d.image_ids[0]) : ''" fit="cover" class="d-img" />
                <div class="d-main">
                  <div class="d-row">
                    <div class="d-title ellipsis">
                      <span v-if="d.ai_meta" class="ai-mini">AI</span>
                      {{ d.title || '未命名' }}
                    </div>
                    <span class="price">{{ d.price > 0 ? fmtMoney(d.price) : '待定价' }}</span>
                  </div>
                  <div class="small d-status">
                    <StatusTag :value="d.status" :map="draftStatusMap" />
                    <span class="muted ellipsis">{{ accounts.nameOf(d.account_id) }}</span>
                    <span v-if="d.status === 'scheduled'" class="muted">· {{ fmtTime(d.scheduled_at) }}</span>
                    <span v-if="d.ai_meta?.uncertain?.length && canEdit(d)" class="pending">· {{ d.ai_meta.uncertain.length }} 项待确认</span>
                  </div>
                  <el-tooltip v-if="d.error" :content="d.error">
                    <div class="small err ellipsis">{{ d.error }}</div>
                  </el-tooltip>
                  <div class="d-ops">
                    <el-button v-if="canEdit(d)" size="small" type="primary" @click="openDraft(d)">{{ d.ai_meta ? '核对' : '编辑' }}</el-button>
                    <el-button v-if="canEdit(d)" size="small" :loading="busy[`pub-${d.id}`]" @click="publishFromList(d)">直接发布</el-button>
                    <el-link v-if="d.item_id" :href="itemUrl(d.item_id)" target="_blank" type="primary" class="small">查看商品</el-link>
                    <el-button size="small" type="danger" link class="d-del" :disabled="d.status === 'publishing'" @click="removeDraft(d)">删除</el-button>
                  </div>
                </div>
              </div>
            </div>
          </el-card>

          <!-- 智能发品提效助手与质检贴士（填满空间，提升专业度与美观度） -->
          <el-card shadow="never" class="publish-guide-card">
            <div class="guide-card-head">
              <span class="guide-card-title">发布小贴士</span>
            </div>

            <div class="guide-items-list">
              <div class="guide-item-row">
                <div class="guide-item-content">
                  <div class="guide-item-name">多拍实拍细节</div>
                  <div class="guide-item-desc">拍全成色细节与瑕疵，AI 识别与定价更精准</div>
                </div>
              </div>

              <div class="guide-item-row">
                <div class="guide-item-content">
                  <div class="guide-item-name">定价与底价</div>
                  <div class="guide-item-desc">设置底价保护，AI 自动议价绝不低于底价</div>
                </div>
              </div>

              <div class="guide-item-row">
                <div class="guide-item-content">
                  <div class="guide-item-name">自动去掉违规内容</div>
                  <div class="guide-item-desc">自动剔除站外联系方式与违规夸大承诺词</div>
                </div>
              </div>

              <div class="guide-item-row">
                <div class="guide-item-content">
                  <div class="guide-item-name">从选品雷达转手</div>
                  <div class="guide-item-desc">支持雷达好货一键带入参数极速转手发品</div>
                </div>
              </div>
            </div>
          </el-card>
        </div>
      </el-col>
    </el-row>
    <LocationPicker
      v-model="locationOpen"
      :account-id="form.account_id"
      :current="effectiveLocation"
      @select="(l: ItemLocation) => (form.location = l)"
    />
  </div>
</template>

<style scoped>
.location-field {
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
  min-width: 0;
  max-width: 100%;
}
/* ---------- 通用 ---------- */
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 15px;
}
.card-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--xh-muted);
}
.w240 {
  width: 240px;
  max-width: 100%;
}
/* el-form-item__content 默认为 flex 横排，让提示文案与标签芯片独占一行 */
.form-tip,
.chips {
  flex-basis: 100%;
}
.mt-s {
  margin-top: 6px;
}
.range {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

/* ---------- 步骤条 ---------- */
.stepper {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
  font-size: 12px;
  color: var(--xh-muted);
}
.stepper li {
  display: flex;
  align-items: center;
  gap: 6px;
}
.stepper li + li::before {
  content: '';
  width: 24px;
  height: 1px;
  background: var(--xh-border);
  margin-right: 2px;
}
.stepper li.done + li::before {
  background: var(--el-color-primary-light-5);
}
.stepper .dot {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  border: 1px solid #d5d9e0;
  background: #fff;
  transition: all 0.2s;
}
.stepper li.done .dot {
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
  color: var(--xh-primary);
}
.stepper li.active {
  color: var(--xh-text);
  font-weight: 500;
}
.stepper li.active .dot {
  border-color: var(--xh-primary);
  background: var(--xh-primary);
  color: #fff;
  box-shadow: 0 0 0 3px var(--el-color-primary-light-8);
}

/* ---------- AI 生成卡片 ---------- */
.ai-card :deep(.el-card__header) {
  background: linear-gradient(120deg, #f1faf6 0%, #ffffff 60%);
}
.ai-badge {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: linear-gradient(135deg, #2bb57d 0%, #1e9e6a 55%, #15805a 100%);
  box-shadow: 0 2px 6px rgba(30, 158, 106, 0.3);
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.chip {
  border: 1px solid var(--xh-border);
  background: #fff;
  color: #5c6370;
  font-size: 12px;
  line-height: 22px;
  padding: 0 10px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.chip:hover {
  border-color: var(--el-color-primary-light-5);
  color: var(--xh-primary);
}
.chip.on {
  border-color: var(--el-color-primary-light-7);
  background: var(--el-color-primary-light-9);
  color: var(--xh-primary);
}
.strategy-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  width: 100%;
}
.s-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  text-align: left;
  padding: 10px 12px;
  border: 1px solid var(--xh-border);
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  font: inherit;
  line-height: 1.4;
  transition: all 0.15s;
}
.s-card:hover {
  border-color: var(--el-color-primary-light-5);
}
.s-card.on {
  border-color: var(--xh-primary);
  background: var(--el-color-primary-light-9);
  box-shadow: 0 0 0 1px var(--xh-primary) inset;
}
.s-title {
  font-weight: 600;
  color: var(--xh-text);
}
.s-card.on .s-title {
  color: var(--el-color-primary-dark-2);
}
.s-desc {
  font-size: 12px;
  color: var(--xh-muted);
}
.gen-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin: auto -20px -20px;
  padding: 14px 20px;
  border-top: 1px solid var(--xh-border);
  background: #fafbfc;
  border-radius: 0 0 10px 10px;
}
.gen-note {
  font-size: 12px;
  color: var(--xh-muted);
}
.gen-btn-group {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.gen-btn {
  min-width: 180px;
  flex-shrink: 0;
}
.gen-btn:not(.is-disabled) {
  background: linear-gradient(135deg, #2bb57d 0%, #1e9e6a 60%, #187e55 100%);
  border: none;
  box-shadow: 0 4px 12px rgba(30, 158, 106, 0.28);
  transition:
    transform 0.15s,
    box-shadow 0.15s;
}
.gen-btn:not(.is-disabled):hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(30, 158, 106, 0.35);
}
.gen-progress {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}
.g-step {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #b0b6c0;
}
.g-step.done {
  color: var(--xh-primary);
}
.g-step.active {
  color: var(--xh-text);
  font-weight: 500;
}
.g-step.active .el-icon {
  color: var(--xh-primary);
}
.g-dot {
  width: 6px;
  height: 6px;
  margin: 0 4px;
  border-radius: 50%;
  background: currentColor;
}

/* ---------- 页面整体与卡片高度撑满 ---------- */
.publish-page {
  min-height: calc(100vh - 56px - 40px);
  display: flex;
  flex-direction: column;
}
.publish-row {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
}
@media (min-width: 992px) {
  .publish-left-col,
  .publish-right-col {
    display: flex;
    flex-direction: column;
  }
}
.publish-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  border-radius: 10px;
  border-color: var(--xh-border);
}
.publish-card :deep(.el-card__body) {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.publish-form {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.publish-form-actions {
  margin-top: auto;
  padding-top: 16px;
}
.ai-card :deep(.zone .el-upload-dragger) {
  padding: 38px 16px;
}

/* ---------- 草稿与侧边栏 ---------- */
.publish-sidebar-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
  position: sticky;
  top: 0;
}
.drafts {
  flex: 1;
  display: flex;
  flex-direction: column;
  border-radius: 10px;
  border-color: var(--xh-border);
}
.drafts :deep(.el-card__body) {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.drafts :deep(.el-empty) {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
}
.d-filter {
  margin-top: 10px;
}
.draft-list {
  flex: 1;
  min-height: 120px;
  max-height: 480px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-right: 2px;
}
.publish-guide-card {
  flex-shrink: 0;
  border-radius: 10px;
  border-color: var(--xh-border);
  background: #fbfcfe;
}
.guide-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px dashed var(--xh-border);
}
.guide-card-title {
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
}
.guide-items-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.guide-item-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.guide-item-content {
  flex: 1;
}
.guide-item-name {
  font-size: 12.5px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 2px;
}
.guide-item-desc {
  font-size: 11.5px;
  color: #64748b;
  line-height: 1.45;
}
.draft {
  display: flex;
  gap: 12px;
  padding: 10px;
  margin: 0 -10px;
  border-radius: 10px;
  border: 1px solid transparent;
  transition: background 0.15s;
}
.draft:hover {
  background: #f7f9fa;
}
.draft.editing {
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-7);
}
.d-img {
  width: 64px;
  height: 64px;
  border-radius: 8px;
  flex-shrink: 0;
  background: #f2f3f5;
  border: 1px solid var(--xh-border);
}
.d-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.d-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.d-title {
  font-weight: 600;
  min-width: 0;
}
.ai-mini {
  display: inline-block;
  font-size: 10px;
  line-height: 16px;
  padding: 0 5px;
  margin-right: 2px;
  border-radius: 4px;
  color: #fff;
  background: var(--xh-primary);
  vertical-align: 1px;
  font-weight: 500;
}
.d-status {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.pending {
  color: var(--el-color-warning-dark-2);
  white-space: nowrap;
}
.d-ops {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}
.d-ops .el-button + .el-button {
  margin-left: 0;
}
.d-del {
  margin-left: auto !important;
}
.price {
  color: #f56c6c;
  font-weight: 600;
  white-space: nowrap;
}
.err {
  color: var(--el-color-danger);
}
.ai-icon {
  vertical-align: -2px;
  color: var(--xh-primary);
}
.ml {
  margin-left: 6px;
}
.mb {
  margin-bottom: 10px;
}
.confirm-box {
  border: 1px solid var(--el-color-warning-light-5);
  background: var(--el-color-warning-light-9);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.confirm-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  margin-bottom: 4px;
  color: var(--el-color-warning-dark-2);
}
.confirm-item {
  display: flex;
  height: auto;
  min-height: 28px;
  white-space: normal;
  line-height: 1.5;
  margin-right: 0;
}
.ai-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 12px;
}
.alt-titles {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
}
.alt {
  cursor: pointer;
  max-width: 100%;
}
.strategy {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
}
.strategy .el-button + .el-button {
  margin-left: 0;
}
@media (max-width: 768px) {
  .strategy-cards {
    grid-template-columns: 1fr;
  }
  .gen-footer {
    flex-direction: column;
    align-items: stretch;
  }
  .gen-btn {
    width: 100%;
  }
}
</style>
