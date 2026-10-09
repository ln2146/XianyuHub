<script setup lang="ts">
/**
 * 发布商品：AI 优先。
 * 1. 上传图片（+ 一句话说明、定价策略）→ AI 生成整份草稿（标题、描述、价格、底价、运费、知识库）
 * 2. 确认页：逐项核对 AI 标出的待确认事项，按需修改 → 确认发布
 * 也可以切换为“手动填写”。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type UploadRequestOptions } from 'element-plus'
import { Close, EditPen, MagicStick, Plus, Refresh, Star, Warning } from '@element-plus/icons-vue'
import {
  aiDraft,
  createDraft,
  deleteDraft,
  listDrafts,
  publishDraft,
  updateDraft,
  uploadImage,
  uploadUrl,
  type AiMeta,
  type DraftIn,
  type DraftOut,
  type PriceStrategy,
  type ShippingMode,
} from '@/api/goods'
import MarketPanel from '@/components/MarketPanel.vue'
import StatusTag from '@/components/StatusTag.vue'
import { useAccountsStore } from '@/stores/accounts'
import { useMobile } from '@/composables/useMobile'
import { draftStatusMap, fmtMoney, fmtTime, itemUrl } from '@/utils/format'

const accounts = useAccountsStore()
const isMobile = useMobile()

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
  scheduled_at: Date | null
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
  scheduled_at: null,
})

const form = reactive<FormState>(emptyForm())
const editingId = ref<number | null>(null)
const aiMeta = ref<AiMeta | null>(null)
const confirmed = reactive<Record<number, boolean>>({})
const saving = ref(false)
const publishing = ref(false)
const uploading = ref(0)

const gen = reactive({ hint: '', strategy: 'market' as PriceStrategy, loading: false, elapsed: 0 })
let timer: number | undefined

const strategyLabel: Record<PriceStrategy, string> = { quick: '快速出手', market: '市场价', premium: '高价试水' }
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

// ---------------------------------------------------------------- 图片上传
async function onUpload(opt: UploadRequestOptions) {
  if (form.image_ids.length >= 9) {
    ElMessage.warning('最多 9 张图片')
    return
  }
  uploading.value += 1
  try {
    const r = await uploadImage(opt.file)
    if (form.image_ids.length < 9) form.image_ids.push(r.id)
  } catch {
    /* 拦截器已提示 */
  } finally {
    uploading.value -= 1
  }
}

function beforeUpload(file: File) {
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('只能上传图片')
    return false
  }
  if (file.size > 10 * 1024 * 1024) {
    ElMessage.warning('单张图片不超过 10MB')
    return false
  }
  return true
}

function removeImage(i: number) {
  form.image_ids.splice(i, 1)
}
function makeCover(i: number) {
  const [id] = form.image_ids.splice(i, 1)
  if (id) form.image_ids.unshift(id)
}

// ---------------------------------------------------------------- AI 生成
const genStage = computed(() => {
  const t = gen.elapsed
  if (t < 15) return '正在识别图片中的商品…'
  if (t < 35) return '正在撰写标题、描述和常见问题…'
  if (t < 60) return '正在查询同款行情、计算售价与底价…'
  return '快好了，部分模型需要 1~2 分钟，请稍候…'
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
    scheduled_at: form.scheduled_at ? form.scheduled_at.toISOString() : null,
  }
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
  if (pending) lines.unshift(`⚠️ 还有 ${pending} 项 AI 标注的信息未确认。`)
  return lines.join('\n')
}

/** 确认页：保存修改后立即发布 */
async function confirmAndPublish() {
  const body = toBody()
  if (!body) return
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

onMounted(async () => {
  loadDrafts()
  await accounts.load().catch(() => undefined)
  if (!form.account_id) form.account_id = accounts.list[0]?.id ?? null
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>商品中心 · 发布</h2>
        <div class="sub">上传图片 → AI 生成整份商品信息 → 你核对确认 → 发布</div>
      </div>
      <div>
        <el-button v-if="mode !== 'ai'" :icon="MagicStick" @click="resetAll">新的 AI 发布</el-button>
        <el-button v-if="mode === 'ai'" :icon="EditPen" link type="primary" @click="mode = 'manual'">不用 AI，手动填写</el-button>
      </div>
    </div>

    <el-row :gutter="12">
      <el-col :xs="24" :lg="14">
        <!-- 第一步：上传图片，AI 生成 -->
        <el-card v-if="mode === 'ai'" shadow="never">
          <template #header>
            <div class="card-head">
              <span><el-icon class="ai-icon"><MagicStick /></el-icon> AI 生成商品信息</span>
            </div>
          </template>
          <el-form label-width="90px" :label-position="isMobile ? 'top' : 'right'">
            <el-form-item label="发布账号" required>
              <el-select v-model="form.account_id" placeholder="选择账号" class="w240">
                <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
              </el-select>
            </el-form-item>
            <el-form-item label="商品图片" required>
              <div class="images">
                <div v-for="(id, i) in form.image_ids" :key="id" class="img-item">
                  <el-image :src="uploadUrl(id)" fit="cover" class="img" :preview-src-list="form.image_ids.map(uploadUrl)" :initial-index="i" preview-teleported />
                  <span v-if="i === 0" class="cover">首图</span>
                  <div class="img-ops">
                    <el-button :icon="Close" size="small" circle title="移除" @click="removeImage(i)" />
                  </div>
                </div>
                <el-upload v-if="form.image_ids.length < 9" :show-file-list="false" :http-request="onUpload" :before-upload="beforeUpload" accept="image/*" multiple>
                  <div v-loading="uploading > 0" class="uploader">
                    <el-icon :size="22"><Plus /></el-icon>
                    <span class="small">{{ form.image_ids.length }}/9</span>
                  </div>
                </el-upload>
              </div>
              <div class="form-tip">建议包含正面、背面、细节和瑕疵特写；AI 会自动挑选封面。</div>
            </el-form-item>
            <el-form-item label="一句话说明">
              <el-input
                v-model="gen.hint"
                type="textarea"
                :rows="2"
                maxlength="500"
                show-word-limit
                placeholder="可选。例如：自用一年，屏幕无划痕，带原装充电器，1500 出，最低 1300"
              />
              <div class="form-tip">写了价格会优先采用；没写则按同款行情和下面的策略定价。</div>
            </el-form-item>
            <el-form-item label="定价策略">
              <el-radio-group v-model="gen.strategy">
                <el-radio-button v-for="(label, k) in strategyLabel" :key="k" :value="k">{{ label }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" size="large" :icon="MagicStick" :loading="gen.loading" :disabled="!form.image_ids.length || uploading > 0" @click="generate(false)">
                {{ gen.loading ? `生成中 ${gen.elapsed}s` : 'AI 生成商品信息' }}
              </el-button>
            </el-form-item>
            <el-alert v-if="gen.loading" :title="genStage" type="info" :closable="false" show-icon />
          </el-form>
        </el-card>

        <!-- 第二步：确认页（AI 草稿）/ 手动填写 -->
        <el-card v-else shadow="never">
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

          <el-form label-width="90px" :label-position="isMobile ? 'top' : 'right'">
            <el-form-item label="发布账号" required>
              <el-select v-model="form.account_id" placeholder="选择账号" class="w240">
                <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
              </el-select>
            </el-form-item>
            <el-form-item label="图片" required>
              <div class="images">
                <div v-for="(id, i) in form.image_ids" :key="id" class="img-item">
                  <el-image :src="uploadUrl(id)" fit="cover" class="img" :preview-src-list="form.image_ids.map(uploadUrl)" :initial-index="i" preview-teleported />
                  <span v-if="i === 0" class="cover">首图</span>
                  <div class="img-ops">
                    <el-button v-if="i > 0" :icon="Star" size="small" circle title="设为首图" @click="makeCover(i)" />
                    <el-button :icon="Close" size="small" circle title="移除" @click="removeImage(i)" />
                  </div>
                </div>
                <el-upload v-if="form.image_ids.length < 9" :show-file-list="false" :http-request="onUpload" :before-upload="beforeUpload" accept="image/*" multiple>
                  <div v-loading="uploading > 0" class="uploader">
                    <el-icon :size="22"><Plus /></el-icon>
                    <span class="small">{{ form.image_ids.length }}/9</span>
                  </div>
                </el-upload>
              </div>
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
              <div class="form-tip">AI 议价的最低价，不会展示给买家。不设置则 AI 不会给出任何低于售价的价格。</div>
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
            <el-form-item label="客服知识库">
              <el-input v-model="form.knowledge" type="textarea" :rows="aiMeta ? 8 : 3" placeholder="可选：FAQ、参数、瑕疵说明等，发布后供 AI 客服回答买家" />
              <div v-if="aiMeta" class="form-tip">AI 已根据图片和说明生成常见问答，发布后 AI 客服会据此回答买家，请检查是否准确。</div>
            </el-form-item>
            <el-form-item label="虚拟商品">
              <el-switch v-model="form.is_virtual" />
            </el-form-item>
            <el-form-item label="定时发布">
              <el-date-picker v-model="form.scheduled_at" type="datetime" placeholder="留空表示立即发布" :disabled-date="(d: Date) => d.getTime() < Date.now() - 86400000" />
            </el-form-item>

            <el-collapse v-if="aiMeta?.market" class="mb">
              <el-collapse-item :title="`同款行情（关键词「${aiMeta.market.keyword}」，${aiMeta.market.sample} 个样本）`">
                <MarketPanel :data="aiMeta.market" :my-price="form.price" @pick="pickPrice" />
              </el-collapse-item>
            </el-collapse>

            <el-form-item>
              <el-button type="primary" :loading="publishing" :disabled="gen.loading" @click="confirmAndPublish">
                {{ form.scheduled_at ? '确认并定时发布' : '确认并发布' }}
              </el-button>
              <el-button :loading="saving" :disabled="gen.loading" @click="saveDraft">保存草稿</el-button>
              <el-button v-if="mode === 'manual' && !editingId" link type="primary" @click="mode = 'ai'">改用 AI 生成</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="10">
        <el-card shadow="never" class="drafts">
          <template #header>
            <div class="card-head">
              <span>草稿与发布记录</span>
              <el-button :icon="Refresh" link :loading="draftsLoading" @click="loadDrafts">刷新</el-button>
            </div>
          </template>
          <el-empty v-if="!draftsLoading && !drafts.length" description="暂无草稿" :image-size="60" />
          <div v-loading="draftsLoading" class="draft-list">
            <div v-for="d in drafts" :key="d.id" class="draft" :class="{ editing: editingId === d.id }">
              <el-image :src="d.image_ids[0] ? uploadUrl(d.image_ids[0]) : ''" fit="cover" class="d-img" />
              <div class="d-main">
                <div class="d-title ellipsis">
                  <el-tag v-if="d.ai_meta" size="small" type="success" effect="plain">AI</el-tag>
                  {{ d.title || '未命名' }}
                </div>
                <div class="small">
                  <span class="price">{{ d.price > 0 ? fmtMoney(d.price) : '待定价' }}</span>
                  <span class="muted"> · {{ accounts.nameOf(d.account_id) }}</span>
                </div>
                <div class="small d-status">
                  <StatusTag :value="d.status" :map="draftStatusMap" />
                  <span v-if="d.status === 'scheduled'" class="muted">{{ fmtTime(d.scheduled_at) }}</span>
                  <span v-if="d.ai_meta?.uncertain?.length && canEdit(d)" class="muted">· {{ d.ai_meta.uncertain.length }} 项待确认</span>
                  <el-link v-if="d.item_id" :href="itemUrl(d.item_id)" target="_blank" type="primary" class="small">查看商品</el-link>
                </div>
                <el-tooltip v-if="d.error" :content="d.error">
                  <div class="small err ellipsis">{{ d.error }}</div>
                </el-tooltip>
                <div class="d-ops">
                  <el-button v-if="canEdit(d)" size="small" type="primary" @click="openDraft(d)">{{ d.ai_meta ? '核对' : '编辑' }}</el-button>
                  <el-button v-if="canEdit(d)" size="small" :loading="busy[`pub-${d.id}`]" @click="publishFromList(d)">直接发布</el-button>
                  <el-button size="small" type="danger" plain :disabled="d.status === 'publishing'" @click="removeDraft(d)">删除</el-button>
                </div>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.w240 {
  width: 240px;
  max-width: 100%;
}
.images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.img-item {
  position: relative;
  width: 88px;
  height: 88px;
}
.img {
  width: 88px;
  height: 88px;
  border-radius: 8px;
  border: 1px solid var(--xh-border);
}
.cover {
  position: absolute;
  left: 0;
  bottom: 0;
  background: rgba(30, 158, 106, 0.85);
  color: #fff;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 0 6px 0 8px;
}
.img-ops {
  position: absolute;
  right: -6px;
  top: -6px;
  display: flex;
  gap: 2px;
}
.img-ops .el-button + .el-button {
  margin-left: 0;
}
.uploader {
  width: 88px;
  height: 88px;
  border: 1px dashed #c0c4cc;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--xh-muted);
  cursor: pointer;
}
.uploader:hover {
  border-color: var(--xh-primary);
  color: var(--xh-primary);
}
.ai-row {
  display: flex;
  gap: 8px;
  width: 100%;
}
.ai-result {
  width: 100%;
  background: #fafbfc;
  border: 1px solid var(--xh-border);
  border-radius: 8px;
  padding: 12px;
}
.ai-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 8px;
}
.ai-title {
  padding: 6px 10px;
  margin-top: 4px;
  border-radius: 6px;
  background: #fff;
  border: 1px solid var(--xh-border);
  cursor: pointer;
  line-height: 1.5;
}
.ai-title:hover,
.ai-title.on {
  border-color: var(--xh-primary);
  background: var(--el-color-primary-light-9);
}
.ai-desc {
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.6;
  max-height: 160px;
  overflow: auto;
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
.drafts {
  position: sticky;
  top: 0;
}
.draft-list {
  min-height: 60px;
}
.draft {
  display: flex;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid var(--xh-border);
}
.draft.editing {
  background: var(--el-color-primary-light-9);
}
.d-img {
  width: 64px;
  height: 64px;
  border-radius: 6px;
  flex-shrink: 0;
  background: #f2f3f5;
}
.d-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.d-title {
  font-weight: 600;
}
.d-status {
  display: flex;
  align-items: center;
  gap: 6px;
}
.d-ops {
  display: flex;
  gap: 6px;
  margin-top: 4px;
}
.d-ops .el-button + .el-button {
  margin-left: 0;
}
.price {
  color: #f56c6c;
  font-weight: 600;
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
  .ai-row {
    flex-direction: column;
  }
}
</style>
