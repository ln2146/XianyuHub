<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatDotRound,
  Check,
  Connection,
  Cpu,
  Delete,
  Download,
  Edit,
  Key,
  Lightning,
  Link,
  Picture,
  Plus,
  Refresh,
  RefreshRight,
  Setting,
} from '@element-plus/icons-vue'
import {
  createLlmProvider,
  deleteLlmProvider,
  fetchLlmModels,
  getLlmMeta,
  getLlmStatus,
  getLlmTiers,
  listLlmProviders,
  testLlmProvider,
  updateLlmProvider,
  updateLlmTiers,
  type LlmKind,
  type LlmPreset,
  type LlmProvider,
  type LlmStatus,
  type TierItem,
} from '@/api/llm'
import { errorMessage } from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useMobile } from '@/composables/useMobile'
import { fmtTime } from '@/utils/format'

const auth = useAuthStore()
const isMobile = useMobile()

const loading = ref(false)
const status = ref<LlmStatus | null>(null)
const providers = ref<LlmProvider[]>([])
const presets = ref<LlmPreset[]>([])
const busy = reactive<Record<string, boolean>>({})

// 场景模型绑定表单 (格式: `${provider_id}:${model}`)
const tierForm = reactive({
  chat: '',
  vision: '',
  fast: '',
})
const savedTiers = reactive({
  chat: '',
  vision: '',
  fast: '',
})
const tierSaving = ref(false)

const hasUnsavedTierChanges = computed(() => {
  return (
    tierForm.chat !== savedTiers.chat ||
    tierForm.vision !== savedTiers.vision ||
    tierForm.fast !== savedTiers.fast
  )
})

const tierLabels: Record<string, string> = {
  vision: '看图发品与质检',
  chat: '智能客服问答',
  fast: '意图分类与粗筛',
}

const tokenUsed = computed(() =>
  status.value ? status.value.gateway.usage_today.input_tokens + status.value.gateway.usage_today.output_tokens : 0,
)

/** 服务商品牌元信息识别（用于精致的卡片 Logo 与配色） */
function getProviderMeta(name: string) {
  const n = (name || '').toLowerCase()
  if (n.includes('deepseek')) {
    return { brand: 'DeepSeek', color: '#1677ff', bg: 'rgba(22, 119, 255, 0.12)', border: 'rgba(22, 119, 255, 0.25)' }
  }
  if (n.includes('阿里') || n.includes('qwen') || n.includes('tongyi') || n.includes('通义')) {
    return { brand: 'Qwen', color: '#ff6a00', bg: 'rgba(255, 106, 0, 0.12)', border: 'rgba(255, 106, 0, 0.25)' }
  }
  if (n.includes('智谱') || n.includes('glm') || n.includes('zhipu')) {
    return { brand: 'GLM', color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.12)', border: 'rgba(59, 130, 246, 0.25)' }
  }
  if (n.includes('openai') || n.includes('gpt')) {
    return { brand: 'OpenAI', color: '#10a37f', bg: 'rgba(16, 163, 127, 0.12)', border: 'rgba(16, 163, 127, 0.25)' }
  }
  if (n.includes('claude') || n.includes('anthropic')) {
    return { brand: 'Claude', color: '#d97706', bg: 'rgba(217, 119, 6, 0.12)', border: 'rgba(217, 119, 6, 0.25)' }
  }
  if (n.includes('gemini') || n.includes('google')) {
    return { brand: 'Gemini', color: '#4285f4', bg: 'rgba(66, 133, 244, 0.12)', border: 'rgba(66, 133, 244, 0.25)' }
  }
  if (n.includes('kimi') || n.includes('moonshot')) {
    return { brand: 'Kimi', color: '#10b981', bg: 'rgba(16, 185, 129, 0.12)', border: 'rgba(16, 185, 129, 0.25)' }
  }
  if (n.includes('silicon') || n.includes('硅基流动')) {
    return { brand: 'Silicon', color: '#7c3aed', bg: 'rgba(124, 58, 237, 0.12)', border: 'rgba(124, 58, 237, 0.25)' }
  }
  if (n.includes('ollama') || n.includes('local') || n.includes('本地')) {
    return { brand: 'Local', color: '#475569', bg: 'rgba(71, 85, 105, 0.12)', border: 'rgba(71, 85, 105, 0.25)' }
  }
  const clean = (name || '').replace(/[\(\)（）\s]/g, '')
  return {
    brand: clean ? clean.slice(0, 4).toUpperCase() : 'AI',
    color: 'var(--xh-primary)',
    bg: 'var(--xh-primary-soft)',
    border: 'var(--xh-border)',
  }
}

const defaultChatModelName = computed(() => {
  return status.value?.gateway.models.chat || '未配置'
})
const defaultVisionModelName = computed(() => {
  return status.value?.gateway.models.vision || '未配置'
})
const defaultFastModelName = computed(() => {
  return status.value?.gateway.models.fast || '未配置'
})

const activeChatModel = computed(() => {
  if (tierForm.chat) {
    const parts = tierForm.chat.split(':')
    return parts.slice(1).join(':') || tierForm.chat
  }
  return status.value?.gateway.models.chat || '未配置'
})

const activeVisionModel = computed(() => {
  if (tierForm.vision) {
    const parts = tierForm.vision.split(':')
    return parts.slice(1).join(':') || tierForm.vision
  }
  return status.value?.gateway.models.vision || '未配置'
})

const activeFastModel = computed(() => {
  if (tierForm.fast) {
    const parts = tierForm.fast.split(':')
    return parts.slice(1).join(':') || tierForm.fast
  }
  return status.value?.gateway.models.fast || '未配置'
})

function isCustomTier(tierKey: 'chat' | 'vision' | 'fast'): boolean {
  return !!tierForm[tierKey] || !!status.value?.tiers?.[tierKey]?.provider_id
}

function getScenarioProviderName(tierKey: 'chat' | 'vision' | 'fast'): string {
  const formVal = tierForm[tierKey]
  if (formVal) {
    const pid = Number(formVal.split(':')[0])
    const p = providers.value.find((x) => x.id === pid)
    if (p) return `${p.name} · 自定义`
  }
  if (status.value?.tiers?.[tierKey]?.provider_id) {
    const pid = status.value.tiers[tierKey].provider_id
    const p = providers.value.find((x) => x.id === pid)
    if (p) return `${p.name} · 自定义`
  }
  const activeP =
    enabledProviders.value.find((p) => p.name === status.value?.gateway.provider || p.name === status.value?.active_source) ||
    enabledProviders.value[0]
  if (activeP) {
    return `${activeP.name} · 默认继承`
  }
  if (status.value?.active_source) return `${status.value.active_source} · 默认继承`
  return '系统主用 · 默认'
}

function getModelBadge(
  m: ModelOption,
  g: ProviderGroup,
  tier: 'chat' | 'vision' | 'fast',
): { text: string; type: 'success' | 'warning' | 'info' | 'primary' } | null {
  const p = providers.value.find((prov) => prov.id === g.id)
  const name = m.label.toLowerCase()

  // 1. 对应场景核心推荐标识
  if (tier === 'chat' && p?.model_chat === m.label) {
    return { text: '对话推荐', type: 'success' }
  }
  if (tier === 'vision' && (p?.model_vision === m.label || m.isVision)) {
    return { text: '识图推荐', type: 'warning' }
  }
  if (tier === 'fast' && p?.model_fast === m.label) {
    return { text: '快筛推荐', type: 'info' }
  }

  // 2. 根据模型命名特性的通用能力标识
  if (m.isVision || /vl|vision|4v|image/i.test(name)) {
    return { text: '多模态', type: 'warning' }
  }
  if (/flash|fast|mini|turbo|speed|lite|instant/i.test(name)) {
    return { text: '极速', type: 'info' }
  }
  if (/reasoner|thinking|r1|deepseek-r1/i.test(name)) {
    return { text: '深度思考', type: 'primary' }
  }
  if (/max|pro|ultra|plus|opus|large/i.test(name)) {
    return { text: '旗舰', type: 'success' }
  }

  return null
}

function isPresetConnected(presetName: string): boolean {
  return providers.value.some((p) => p.name === presetName || p.name.includes(presetName))
}

function getProviderModels(p: LlmProvider): string[] {
  const set = new Set<string>()
  if (p.model_chat) set.add(p.model_chat)
  if (p.model_vision) set.add(p.model_vision)
  if (p.model_fast) set.add(p.model_fast)
  if (p.custom_models) {
    p.custom_models.forEach((m) => m && set.add(m))
  }
  const preset = presets.value.find((x) => x.name === p.name || x.id === p.name.toLowerCase())
  if (preset) {
    if (preset.models?.chat) set.add(preset.models.chat)
    if (preset.models?.vision) set.add(preset.models.vision)
    if (preset.models?.fast) set.add(preset.models.fast)
    if (preset.suggested_models) {
      preset.suggested_models.forEach((m) => m && set.add(m))
    }
  }
  return Array.from(set).filter(Boolean)
}

const enabledProviders = computed(() => providers.value.filter((p) => p.enabled))

interface ModelOption {
  value: string
  label: string
  isVision: boolean
}

interface ProviderGroup {
  id: number
  name: string
  models: ModelOption[]
}

const providerModelGroups = computed<ProviderGroup[]>(() => {
  return enabledProviders.value.map((p) => {
    const rawModels = getProviderModels(p)
    return {
      id: p.id,
      name: p.name,
      models: rawModels.map((m) => ({
        value: `${p.id}:${m}`,
        label: m,
        isVision: /vl|vision|4v|gemini|image|gpt-4o|claude/i.test(m) || m === p.model_vision,
      })),
    }
  })
})

const visionGroups = computed(() => {
  return providerModelGroups.value
    .map((g) => ({
      ...g,
      models: g.models.filter(
        (m) =>
          m.isVision ||
          g.name.includes('阿里') ||
          g.name.includes('智谱') ||
          g.name.includes('OpenAI') ||
          g.name.includes('Claude') ||
          g.name.includes('Gemini'),
      ),
    }))
    .filter((g) => g.models.length > 0)
})

const hasConnectedVisionModel = computed(() => {
  return enabledProviders.value.some(
    (p) =>
      p.model_vision ||
      getProviderModels(p).some((m) => /vl|vision|4v|image|gemini|gpt-4o|claude/i.test(m)),
  )
})

async function load() {
  loading.value = true
  try {
    status.value = await getLlmStatus()
    if (auth.isAdmin) {
      const [meta, list, tiers] = await Promise.all([
        getLlmMeta(),
        listLlmProviders(),
        getLlmTiers().catch(() => ({}) as Record<string, TierItem>),
      ])
      presets.value = meta.presets
      providers.value = list

      // 同步当前分场景模型选择
      const chatTarget = tiers.chat || status.value.tiers?.chat
      if (chatTarget?.provider_id && chatTarget.model) {
        tierForm.chat = `${chatTarget.provider_id}:${chatTarget.model}`
      } else {
        tierForm.chat = ''
      }

      const visionTarget = tiers.vision || status.value.tiers?.vision
      if (visionTarget?.provider_id && visionTarget.model) {
        tierForm.vision = `${visionTarget.provider_id}:${visionTarget.model}`
      } else {
        tierForm.vision = ''
      }

      const fastTarget = tiers.fast || status.value.tiers?.fast
      if (fastTarget?.provider_id && fastTarget.model) {
        tierForm.fast = `${fastTarget.provider_id}:${fastTarget.model}`
      } else {
        tierForm.fast = ''
      }

      savedTiers.chat = tierForm.chat
      savedTiers.vision = tierForm.vision
      savedTiers.fast = tierForm.fast
    }
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function saveTiers() {
  tierSaving.value = true
  try {
    const parse = (val: string) => {
      if (!val) return { provider_id: null, model: '' }
      const [pid, ...rest] = val.split(':')
      return { provider_id: Number(pid), model: rest.join(':') }
    }
    await updateLlmTiers({
      chat: parse(tierForm.chat),
      vision: parse(tierForm.vision),
      fast: parse(tierForm.fast),
    })
    savedTiers.chat = tierForm.chat
    savedTiers.vision = tierForm.vision
    savedTiers.fast = tierForm.fast
    ElMessage.success('场景模型配置已保存并生效')
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    tierSaving.value = false
  }
}

// ---------------------------------------------------------------- 接入模态框
const presetCategoryFilter = ref('all')
const categories = [
  { key: 'all', label: '全部服务商' },
  { key: 'cn', label: '国内主流' },
  { key: 'global', label: '国际服务' },
  { key: 'aggregator', label: '聚合分发' },
  { key: 'local', label: '本地与自建' },
]

const filteredPresets = computed(() => {
  if (presetCategoryFilter.value === 'all') return presets.value
  return presets.value.filter((p) => p.category === presetCategoryFilter.value || p.id === 'custom')
})

const edit = reactive({
  open: false,
  saving: false,
  testing: false,
  fetching: false,
  id: null as number | null,
  preset: 'deepseek',
  name: '',
  kind: 'openai_compatible' as LlmKind,
  base_url: '',
  api_key: '',
  model_vision: '',
  model_chat: '',
  model_fast: '',
  custom_models: [] as string[],
  new_model_tag: '',
  timeout_seconds: 90,
  anthropic_fallbacks: true,
  daily_token_budget: null as number | null,
  enabled: true,
  masked: '',
  has_key: false,
  orig_kind: '' as string,
  orig_base_url: '',
})

const remoteFetchedModels = ref<string[]>([])

const normUrl = (u: string) => u.trim().replace(/\/+$/, '')
const needsNewKey = computed(
  () =>
    !!edit.id &&
    edit.has_key &&
    (!edit.api_key.trim() || edit.api_key.includes('***')) &&
    (edit.kind !== edit.orig_kind || normUrl(edit.base_url) !== normUrl(edit.orig_base_url)),
)
const KEY_REBIND_TIP = '修改了接口地址，请重新填写 API Key（已保存的 Key 不会发往新的地址）'
const activePreset = computed(() => presets.value.find((x) => x.id === edit.preset))

const suggestedPresetModels = computed(() => {
  const p = activePreset.value
  if (!p) return []
  const list = [p.models.chat, p.models.vision, p.models.fast, ...(p.suggested_models || [])].filter(Boolean)
  return Array.from(new Set(list))
})

function toggleModel(model: string) {
  if (edit.custom_models.includes(model)) {
    edit.custom_models = edit.custom_models.filter((m) => m !== model)
  } else {
    edit.custom_models.push(model)
  }
}

function addAllSuggested() {
  const merged = new Set([...edit.custom_models, ...suggestedPresetModels.value])
  edit.custom_models = Array.from(merged)
}

function addAllRemote() {
  const merged = new Set([...edit.custom_models, ...remoteFetchedModels.value])
  edit.custom_models = Array.from(merged)
}

const baseUrlPlaceholder = computed(() => {
  if (edit.preset === 'dashscope') return 'https://dashscope.aliyuncs.com/compatible-mode/v1'
  if (edit.preset === 'deepseek') return 'https://api.deepseek.com/v1'
  if (edit.preset === 'openai') return 'https://api.openai.com/v1'
  if (edit.preset === 'claude') return '默认 Anthropic 官方端点（留空即可）'
  if (edit.preset === 'gemini') return 'https://generativelanguage.googleapis.com/v1beta/openai'
  if (edit.preset === 'zhipu') return 'https://open.bigmodel.cn/api/paas/v4'
  if (edit.preset === 'doubao') return 'https://ark.cn-beijing.volces.com/api/v3'
  if (edit.preset === 'moonshot') return 'https://api.moonshot.cn/v1'
  if (edit.preset === 'siliconflow') return 'https://api.siliconflow.cn/v1'
  if (edit.preset === 'openrouter') return 'https://openrouter.ai/api/v1'
  if (edit.preset === 'ollama') return 'http://127.0.0.1:11434/v1'
  return '例如 https://api.deepseek.com/v1'
})

function applyPreset(id: string) {
  const p = presets.value.find((x) => x.id === id)
  if (!p) return
  edit.kind = (p.kind || 'openai_compatible') as LlmKind
  edit.base_url = p.base_url
  edit.model_vision = ''
  edit.model_chat = ''
  edit.model_fast = ''
  if (!edit.id) {
    edit.name = p.name === '自定义配置' ? '' : p.name
    edit.custom_models = []
  }
  remoteFetchedModels.value = []
}

function selectPreset(id: string) {
  edit.preset = id
  applyPreset(id)
}

function openCreate(presetId = 'deepseek') {
  presetCategoryFilter.value = 'all'
  remoteFetchedModels.value = []
  Object.assign(edit, {
    open: true,
    id: null,
    preset: presetId,
    name: '',
    kind: 'openai_compatible' as LlmKind,
    base_url: '',
    api_key: '',
    model_vision: '',
    model_chat: '',
    model_fast: '',
    custom_models: [],
    new_model_tag: '',
    timeout_seconds: 90,
    anthropic_fallbacks: true,
    daily_token_budget: null,
    enabled: true,
    masked: '',
    has_key: false,
    orig_kind: '',
    orig_base_url: '',
  })
  applyPreset(presetId)
}

function openEdit(p: LlmProvider) {
  const presetMatch = presets.value.find((x) => x.name === p.name || x.base_url === p.base_url)
  const allModels = getProviderModels(p)
  remoteFetchedModels.value = []

  Object.assign(edit, {
    open: true,
    id: p.id,
    preset: presetMatch?.id || 'custom',
    name: p.name,
    kind: p.kind,
    base_url: p.base_url,
    api_key: '',
    model_vision: p.model_vision,
    model_chat: p.model_chat,
    model_fast: p.model_fast,
    custom_models: allModels,
    new_model_tag: '',
    timeout_seconds: p.timeout_seconds,
    anthropic_fallbacks: p.anthropic_fallbacks,
    daily_token_budget: p.daily_token_budget,
    enabled: p.enabled,
    masked: p.api_key_masked,
    has_key: p.has_api_key,
    orig_kind: p.kind,
    orig_base_url: p.base_url,
  })
}

function addModelTag() {
  const val = edit.new_model_tag.trim()
  if (val && !edit.custom_models.includes(val)) {
    edit.custom_models.push(val)
    if (!edit.model_chat) edit.model_chat = val
  }
  edit.new_model_tag = ''
}

function removeModelTag(tag: string) {
  edit.custom_models = edit.custom_models.filter((m) => m !== tag)
}

function payload() {
  const custom = edit.custom_models
  const first = custom[0] || ''
  const visionCandidate = custom.find((m) => /vl|vision|4v|image|gpt-4o|claude|gemini/i.test(m)) || first
  return {
    name: edit.name.trim(),
    kind: edit.kind,
    base_url: edit.base_url.trim(),
    api_key: edit.api_key,
    model_vision: edit.model_vision.trim() || visionCandidate,
    model_chat: edit.model_chat.trim() || first,
    model_fast: edit.model_fast.trim() || first,
    custom_models: custom,
    timeout_seconds: edit.timeout_seconds || 90,
    anthropic_fallbacks: edit.anthropic_fallbacks ?? true,
    daily_token_budget: edit.daily_token_budget,
  }
}

function validate(): boolean {
  if (!edit.name.trim()) {
    ElMessage.warning('请填写服务商名称')
    return false
  }
  if (edit.kind !== 'anthropic' && !edit.base_url.trim()) {
    ElMessage.warning('请填写接口地址')
    return false
  }
  if (!edit.id && !edit.api_key.trim()) {
    ElMessage.warning('请填写 API Key')
    return false
  }
  if (!edit.custom_models.length) {
    ElMessage.warning('请至少选择或添加一个可用模型')
    return false
  }
  if (needsNewKey.value) {
    ElMessage.warning(KEY_REBIND_TIP)
    return false
  }
  return true
}

async function save() {
  if (!validate()) return
  edit.saving = true
  try {
    const data = payload()
    if (edit.id) {
      await updateLlmProvider(edit.id, { ...data, enabled: edit.enabled })
      ElMessage.success('已更新服务商配置')
    } else {
      await createLlmProvider({ ...data, enabled: edit.enabled, activate: false })
      ElMessage.success('已成功接入服务商！已可在上方配置中按需选用')
    }
    edit.open = false
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    edit.saving = false
  }
}

async function probe() {
  if (!validate()) return
  edit.testing = true
  try {
    const body = { ...payload(), id: edit.id ?? undefined }
    const r = await testLlmProvider(body)
    if (r.ok) ElMessage.success(`连接成功（${r.model}）：${r.message}`)
    else ElMessage.error(`连接失败：${r.message}`)
  } catch {
    /* 拦截器已提示 */
  } finally {
    edit.testing = false
  }
}

async function pullModels() {
  if (edit.kind !== 'anthropic' && !edit.base_url.trim()) return ElMessage.warning('请先填写接口地址')
  if (!edit.api_key.trim() && !edit.has_key) {
    return ElMessage.warning('请先填写 API Key，服务商需鉴权后才能获取可用模型')
  }
  if (needsNewKey.value) return ElMessage.warning(KEY_REBIND_TIP)
  edit.fetching = true
  try {
    const r = await fetchLlmModels({ ...payload(), id: edit.id ?? undefined })
    if (r.models.length) {
      remoteFetchedModels.value = r.models
      ElMessage.success(`拉取成功！已查询到 ${r.models.length} 个可用模型，可在下方点击选择`)
    } else {
      ElMessage.warning('接口未返回可用模型列表，请直接点击推荐模型或手动添加')
    }
  } catch {
    /* 拦截器已统一展示错误提示，避免重复弹窗 */
  } finally {
    edit.fetching = false
  }
}

// ---------------------------------------------------------------- 服务商列表操作
async function test(p: LlmProvider) {
  busy[`t-${p.id}`] = true
  try {
    const r = await testLlmProvider({
      id: p.id,
      name: p.name,
      kind: p.kind,
      base_url: p.base_url,
      api_key: '',
      model_vision: p.model_vision,
      model_chat: p.model_chat,
      model_fast: p.model_fast,
      timeout_seconds: p.timeout_seconds,
      anthropic_fallbacks: p.anthropic_fallbacks,
    })
    if (r.ok) ElMessage.success(`连通测试通过（${r.model}）：${r.message}`)
    else ElMessage.error(`连通测试未通过：${r.message}`)
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[`t-${p.id}`] = false
  }
}

async function toggle(p: LlmProvider, enabled: boolean) {
  try {
    await updateLlmProvider(p.id, { enabled })
    p.enabled = enabled
    await load()
  } catch {
    /* 拦截器已提示 */
  }
}

async function remove(p: LlmProvider) {
  try {
    await ElMessageBox.confirm(`确认删除模型接入「${p.name}」？关联的场景将回退或停用`, '删除接入', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteLlmProvider(p.id)
    ElMessage.success('已删除接入')
    await load()
  } catch {
    /* 拦截器已提示 */
  }
}
</script>

<template>
  <div class="page">
    <!-- 1. 现代化页面头部 -->
    <div class="page-head">
      <div class="page-head-left">
        <div class="title-row">
          <div class="title-icon-box">
            <el-icon><Cpu /></el-icon>
          </div>
          <div class="title-text-group">
            <div class="title-with-pill">
              <h2>模型配置</h2>
              <span class="gateway-live-pill" :class="status?.gateway.available ? 'online' : 'offline'">
                <span class="pulse-dot" :class="status?.gateway.available ? 'green' : 'red'"></span>
                <span>{{ status?.gateway.available ? '网关运行中' : '网关未启动' }}</span>
              </span>
            </div>
            <p class="page-subtitle">按场景智能调度大模型，支持客服、识图与快筛跨服务商任意混搭</p>
          </div>
        </div>
      </div>
      <div class="page-head-right">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新状态</el-button>
        <el-button v-if="auth.isAdmin" type="primary" :icon="Plus" @click="openCreate('deepseek')">
          添加服务商
        </el-button>
      </div>
    </div>

    <!-- 2. 业务场景模型调度区块 (无套娃、简约通透) -->
    <div class="content-section">
      <div class="section-head-bar">
        <div class="section-head-left">
          <div class="section-title-wrap">
            <el-icon class="section-title-icon"><Setting /></el-icon>
            <h3 class="section-heading">业务场景模型路由</h3>
          </div>
          <span class="section-subtext">为不同场景指派最适合的生效模型，留空则自动继承主服务商</span>
        </div>
        <div class="section-head-right">
          <el-button
            v-if="auth.isAdmin"
            type="primary"
            :icon="Check"
            :loading="tierSaving"
            :class="{ 'save-btn-unsaved': hasUnsavedTierChanges }"
            @click="saveTiers"
          >
            {{ hasUnsavedTierChanges ? '保存模型配置 (有未生效修改)' : '保存配置' }}
          </el-button>
        </div>
      </div>

      <!-- 3列场景卡片网格 -->
      <div class="scenario-grid">
        <!-- 场景 1: 智能客服问答 -->
        <div class="scenario-card" :class="{ 'is-customized': isCustomTier('chat') }">
          <div class="scenario-card-header">
            <div class="scenario-icon-box chat">
              <el-icon><ChatDotRound /></el-icon>
            </div>
            <div class="scenario-header-text">
              <div class="scenario-title-line">
                <span class="scenario-name">智能客服问答</span>
                <span class="scenario-role-pill chat">对话主力</span>
              </div>
              <p class="scenario-desc">买家消息智能回复、多轮议价谈判与防封打招呼</p>
            </div>
          </div>

          <div class="scenario-selector-block">
            <div class="selector-meta-row">
              <span class="selector-label">生效模型</span>
              <span class="selector-state-pill" :class="isCustomTier('chat') ? 'custom' : 'inherit'">
                {{ isCustomTier('chat') ? '自定义指定' : '跟随主服务商' }}
              </span>
            </div>
            <el-select
              v-model="tierForm.chat"
              :placeholder="`跟随主服务商（${defaultChatModelName}）`"
              clearable
              filterable
              class="full-width scenario-select"
              popper-class="scenario-model-popper"
              :disabled="!auth.isAdmin"
            >
              <el-option
                value=""
                :label="`跟随主服务商（${defaultChatModelName}）`"
              >
                <div class="model-opt-item inherit-row">
                  <div class="model-opt-left">
                    <el-icon class="inherit-icon"><RefreshRight /></el-icon>
                    <span class="inherit-title">跟随主服务商</span>
                    <span class="inherit-desc mono">({{ defaultChatModelName }})</span>
                  </div>
                  <span class="model-opt-badge badge-inherit">系统默认</span>
                </div>
              </el-option>

              <el-option-group
                v-for="g in providerModelGroups"
                :key="g.id"
                :label="`${g.name} (${g.models.length} 个模型)`"
              >
                <el-option
                  v-for="m in g.models"
                  :key="m.value"
                  :value="m.value"
                  :label="`${g.name} · ${m.label}`"
                >
                  <div class="model-opt-item">
                    <div class="model-opt-left">
                      <span class="model-bullet" :class="{ 'bullet-active': tierForm.chat === m.value }"></span>
                      <span class="model-name mono" :title="m.label">{{ m.label }}</span>
                    </div>
                    <span
                      v-if="getModelBadge(m, g, 'chat')"
                      class="model-opt-badge"
                      :class="`badge-${getModelBadge(m, g, 'chat')!.type}`"
                    >
                      {{ getModelBadge(m, g, 'chat')!.text }}
                    </span>
                  </div>
                </el-option>
              </el-option-group>
            </el-select>
          </div>

          <div class="scenario-card-footer">
            <div class="footer-status-indicator">
              <span class="pulse-dot-sm" :class="isCustomTier('chat') ? 'blue' : 'green'"></span>
              <span class="footer-model-label">当前生效：</span>
              <span class="footer-model-name mono">{{ activeChatModel }}</span>
            </div>
            <span class="footer-provider-badge">
              {{ getScenarioProviderName('chat') }}
            </span>
          </div>
        </div>

        <!-- 场景 2: 看图发品与质检 -->
        <div class="scenario-card" :class="{ 'is-customized': isCustomTier('vision') }">
          <div class="scenario-card-header">
            <div class="scenario-icon-box vision">
              <el-icon><Picture /></el-icon>
            </div>
            <div class="scenario-header-text">
              <div class="scenario-title-line">
                <span class="scenario-name">看图发品与质检</span>
                <span class="scenario-role-pill vision">多模态视觉</span>
              </div>
              <p class="scenario-desc">以图搜款、看图提取规格瑕疵文案与成色评估</p>
            </div>
          </div>

          <div class="scenario-selector-block">
            <div class="selector-meta-row">
              <span class="selector-label">生效视觉模型</span>
              <span class="selector-state-pill" :class="isCustomTier('vision') ? 'custom' : 'inherit'">
                {{ isCustomTier('vision') ? '自定义指定' : '跟随主服务商' }}
              </span>
            </div>
            <el-select
              v-model="tierForm.vision"
              :placeholder="`跟随主服务商（${defaultVisionModelName}）`"
              clearable
              filterable
              class="full-width scenario-select"
              popper-class="scenario-model-popper"
              :disabled="!auth.isAdmin"
            >
              <el-option
                value=""
                :label="`跟随主服务商（${defaultVisionModelName}）`"
              >
                <div class="model-opt-item inherit-row">
                  <div class="model-opt-left">
                    <el-icon class="inherit-icon"><RefreshRight /></el-icon>
                    <span class="inherit-title">跟随主服务商</span>
                    <span class="inherit-desc mono">({{ defaultVisionModelName }})</span>
                  </div>
                  <span class="model-opt-badge badge-inherit">系统默认</span>
                </div>
              </el-option>

              <el-option-group
                v-for="g in visionGroups"
                :key="g.id"
                :label="`${g.name} (${g.models.length} 个模型)`"
              >
                <el-option
                  v-for="m in g.models"
                  :key="m.value"
                  :value="m.value"
                  :label="`${g.name} · ${m.label}`"
                >
                  <div class="model-opt-item">
                    <div class="model-opt-left">
                      <span class="model-bullet" :class="{ 'bullet-active': tierForm.vision === m.value }"></span>
                      <span class="model-name mono" :title="m.label">{{ m.label }}</span>
                    </div>
                    <span
                      v-if="getModelBadge(m, g, 'vision')"
                      class="model-opt-badge"
                      :class="`badge-${getModelBadge(m, g, 'vision')!.type}`"
                    >
                      {{ getModelBadge(m, g, 'vision')!.text }}
                    </span>
                  </div>
                </el-option>
              </el-option-group>
            </el-select>
          </div>

          <div class="scenario-card-footer">
            <div class="footer-status-indicator">
              <span class="pulse-dot-sm" :class="isCustomTier('vision') ? 'blue' : 'green'"></span>
              <span class="footer-model-label">当前生效：</span>
              <span class="footer-model-name mono">{{ activeVisionModel }}</span>
            </div>
            <div class="footer-right-tags">
              <span v-if="!hasConnectedVisionModel" class="footer-warn-inline" title="当前服务商模型库中未识别到多模态视觉模型">
                ⚠️ 需识图模型
              </span>
              <span class="footer-provider-badge">
                {{ getScenarioProviderName('vision') }}
              </span>
            </div>
          </div>
        </div>

        <!-- 场景 3: 意图分类与快筛 -->
        <div class="scenario-card" :class="{ 'is-customized': isCustomTier('fast') }">
          <div class="scenario-card-header">
            <div class="scenario-icon-box fast">
              <el-icon><Lightning /></el-icon>
            </div>
            <div class="scenario-header-text">
              <div class="scenario-title-line">
                <span class="scenario-name">意图分类与快筛</span>
                <span class="scenario-role-pill fast">极速快筛</span>
              </div>
              <p class="scenario-desc">买家意图毫秒级分流与转人工过滤，低延迟极低成本</p>
            </div>
          </div>

          <div class="scenario-selector-block">
            <div class="selector-meta-row">
              <span class="selector-label">生效快筛模型</span>
              <span class="selector-state-pill" :class="isCustomTier('fast') ? 'custom' : 'inherit'">
                {{ isCustomTier('fast') ? '自定义指定' : '跟随主服务商' }}
              </span>
            </div>
            <el-select
              v-model="tierForm.fast"
              :placeholder="`跟随主服务商（${defaultFastModelName}）`"
              clearable
              filterable
              class="full-width scenario-select"
              popper-class="scenario-model-popper"
              :disabled="!auth.isAdmin"
            >
              <el-option
                value=""
                :label="`跟随主服务商（${defaultFastModelName}）`"
              >
                <div class="model-opt-item inherit-row">
                  <div class="model-opt-left">
                    <el-icon class="inherit-icon"><RefreshRight /></el-icon>
                    <span class="inherit-title">跟随主服务商</span>
                    <span class="inherit-desc mono">({{ defaultFastModelName }})</span>
                  </div>
                  <span class="model-opt-badge badge-inherit">系统默认</span>
                </div>
              </el-option>

              <el-option-group
                v-for="g in providerModelGroups"
                :key="g.id"
                :label="`${g.name} (${g.models.length} 个模型)`"
              >
                <el-option
                  v-for="m in g.models"
                  :key="m.value"
                  :value="m.value"
                  :label="`${g.name} · ${m.label}`"
                >
                  <div class="model-opt-item">
                    <div class="model-opt-left">
                      <span class="model-bullet" :class="{ 'bullet-active': tierForm.fast === m.value }"></span>
                      <span class="model-name mono" :title="m.label">{{ m.label }}</span>
                    </div>
                    <span
                      v-if="getModelBadge(m, g, 'fast')"
                      class="model-opt-badge"
                      :class="`badge-${getModelBadge(m, g, 'fast')!.type}`"
                    >
                      {{ getModelBadge(m, g, 'fast')!.text }}
                    </span>
                  </div>
                </el-option>
              </el-option-group>
            </el-select>
          </div>

          <div class="scenario-card-footer">
            <div class="footer-status-indicator">
              <span class="pulse-dot-sm" :class="isCustomTier('fast') ? 'blue' : 'green'"></span>
              <span class="footer-model-label">当前生效：</span>
              <span class="footer-model-name mono">{{ activeFastModel }}</span>
            </div>
            <span class="footer-provider-badge">
              {{ getScenarioProviderName('fast') }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 3. 网关运行信息指标条 (极简横向数据条) -->
    <div v-if="status" class="metrics-bar">
      <div class="metric-cell">
        <span class="metric-caption">网关生效来源</span>
        <div class="metric-val-wrap">
          <el-tag v-if="status.using_env" size="small" type="warning" effect="light">.env 环境变量</el-tag>
          <span v-else class="metric-val-text font-medium" :title="status.active_source">{{ status.active_source }}</span>
        </div>
      </div>

      <div class="metric-divider"></div>

      <div class="metric-cell">
        <span class="metric-caption">今日总调用量</span>
        <div class="metric-val-wrap">
          <span class="metric-num-bold">{{ status.gateway.usage_today.calls }}</span>
          <span class="metric-sub-unit">次</span>
        </div>
      </div>

      <div class="metric-divider"></div>

      <div class="metric-cell">
        <span class="metric-caption">Token 消耗统计</span>
        <div class="metric-val-wrap">
          <span class="metric-num-bold">{{ tokenUsed.toLocaleString() }}</span>
          <span class="metric-sub-unit">tokens</span>
          <span v-if="status.gateway.usage_today.budget" class="metric-budget-hint">
            / 上限 {{ status.gateway.usage_today.budget.toLocaleString() }}
          </span>
        </div>
      </div>

      <div class="metric-divider"></div>

      <div class="metric-cell">
        <span class="metric-caption">智能路由状态</span>
        <div class="metric-val-wrap">
          <span class="status-live-pill">
            <span class="pulse-dot green"></span>
            <span>按场景分发中</span>
          </span>
        </div>
      </div>
    </div>

    <!-- 4. 已接入服务商管理 (Connected Providers List) -->
    <div v-if="auth.isAdmin" class="providers-section">
      <div class="section-head-bar">
        <div class="section-head-left">
          <div class="section-title-wrap">
            <el-icon class="section-title-icon"><Connection /></el-icon>
            <h3 class="section-heading">已接入服务商</h3>
          </div>
          <span class="section-count-badge">{{ providers.length }} 个已配置</span>
        </div>
        <div class="section-head-right">
          <el-button text bg size="small" :icon="Plus" @click="openCreate('deepseek')">
            添加服务商
          </el-button>
        </div>
      </div>

      <div v-if="!loading && !providers.length" class="empty-state-card">
        <el-empty description="尚未接入大模型服务商，点击右上角「添加新服务商」自由选用 OpenAI、Claude、DeepSeek、阿里等厂商">
          <el-button type="primary" :icon="Plus" @click="openCreate('deepseek')">立即添加服务商</el-button>
        </el-empty>
      </div>

      <div v-else class="providers-grid">
        <div
          v-for="p in providers"
          :key="p.id"
          class="provider-card"
          :class="{ disabled: !p.enabled }"
        >
          <!-- 卡片头部：品牌 Avatar + 名称 + 状态开关 -->
          <div class="card-top-row">
            <div
              class="provider-brand-box"
              :style="{
                background: getProviderMeta(p.name).bg,
                color: getProviderMeta(p.name).color,
                borderColor: getProviderMeta(p.name).border,
              }"
            >
              <span class="brand-text">{{ getProviderMeta(p.name).brand }}</span>
            </div>

            <div class="provider-info-col">
              <div class="provider-name-line">
                <span class="provider-title">{{ p.name }}</span>
                <el-tag size="small" :type="p.enabled ? 'success' : 'info'" effect="light" round>
                  {{ p.enabled ? '已启用' : '已停用' }}
                </el-tag>
              </div>
              <div class="provider-sub-meta">
                <span class="protocol-badge">{{ p.kind === 'anthropic' ? 'Anthropic 协议' : 'OpenAI 规范' }}</span>
                <div v-if="p.active_tiers && p.active_tiers.length" class="active-tiers-list">
                  <span v-for="t in p.active_tiers" :key="t" class="active-tier-pill">
                    {{ tierLabels[t] || t }}
                  </span>
                </div>
              </div>
            </div>

            <div class="provider-switch-wrap">
              <el-switch :model-value="p.enabled" @change="(v: string | number | boolean) => toggle(p, !!v)" />
            </div>
          </div>

          <!-- 卡片中间：端点、Key与模型 Specs -->
          <div class="provider-specs-card">
            <div class="spec-row">
              <span class="spec-label">
                <el-icon><Link /></el-icon>
                <span>端点</span>
              </span>
              <span class="spec-val mono ellipsis" :title="p.base_url || '官方原生端点'">
                {{ p.base_url || '官方原生端点' }}
              </span>
            </div>

            <div class="spec-row">
              <span class="spec-label">
                <el-icon><Key /></el-icon>
                <span>Key</span>
              </span>
              <span class="spec-val mono">
                {{ p.api_key_masked || '未填写' }}
              </span>
            </div>

            <div class="spec-row models-row">
              <span class="spec-label">
                <el-icon><Cpu /></el-icon>
                <span>模型</span>
              </span>
              <div class="models-chips-wrap">
                <span v-for="m in getProviderModels(p).slice(0, 4)" :key="m" class="model-chip-tag mono">
                  {{ m }}
                </span>
                <span v-if="getProviderModels(p).length > 4" class="more-models-chip">
                  +{{ getProviderModels(p).length - 4 }}
                </span>
              </div>
            </div>
          </div>

          <!-- 卡片底部：连通健康度 + 操作按钮 -->
          <div class="card-bottom-row">
            <div class="health-status-wrap">
              <template v-if="p.last_test_ok === true">
                <span class="health-pill ok">
                  <span class="pulse-dot green"></span>
                  <span>连通正常</span>
                </span>
                <span class="health-time">{{ fmtTime(p.last_test_at) }}</span>
              </template>
              <template v-else-if="p.last_test_ok === false">
                <span class="health-pill fail" :title="p.last_error || ''">
                  <span class="pulse-dot red"></span>
                  <span>连通失败</span>
                </span>
                <span class="health-err-msg ellipsis" :title="p.last_error || ''">{{ p.last_error }}</span>
              </template>
              <span v-else class="health-pill none">
                <span class="pulse-dot gray"></span>
                <span>尚未测试</span>
              </span>
            </div>

            <div class="actions-group">
              <el-button size="small" :icon="Connection" :loading="busy[`t-${p.id}`]" @click="test(p)">测试</el-button>
              <el-button size="small" :icon="Edit" @click="openEdit(p)">编辑</el-button>
              <el-button size="small" type="danger" plain :icon="Delete" @click="remove(p)">删除</el-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 3. 添加 / 编辑新服务商模态框 -->
    <el-dialog
      v-model="edit.open"
      :title="edit.id ? `编辑服务商 · ${edit.name}` : '添加新服务商'"
      :width="isMobile ? '95%' : '760px'"
      :close-on-click-modal="false"
      class="provider-dialog"
    >
      <div class="dialog-body-container">
        <!-- 预设选择区（药丸卡片风格，参考供应商列表设计） -->
        <div v-if="!edit.id" class="preset-selection-panel">
          <div class="preset-filter-row">
            <span class="panel-section-label">预设供应商</span>
            <div class="category-tabs">
              <button
                v-for="cat in categories"
                :key="cat.key"
                class="category-tab-btn"
                :class="{ active: presetCategoryFilter === cat.key }"
                type="button"
                @click="presetCategoryFilter = cat.key"
              >
                {{ cat.label }}
              </button>
            </div>
          </div>

          <div class="preset-pills-container">
            <button
              v-for="p in filteredPresets"
              :key="p.id"
              class="preset-pill-btn"
              :class="{
                active: edit.preset === p.id,
                custom: p.id === 'custom',
                connected: isPresetConnected(p.name),
              }"
              type="button"
              @click="selectPreset(p.id)"
            >
              <span class="pill-title">{{ p.name }}</span>
              <span v-if="isPresetConnected(p.name)" class="pill-dot" title="已接入"></span>
            </button>
          </div>

          <div v-if="activePreset?.note" class="preset-notice-row">
            <span class="notice-icon">💡</span>
            <span class="notice-text">{{ activePreset.note }}</span>
          </div>
        </div>

        <el-form label-width="96px" :label-position="isMobile ? 'top' : 'right'" class="provider-form">
          <el-row :gutter="16">
            <el-col :xs="24" :sm="14">
              <el-form-item label="服务商名称" required>
                <el-input v-model="edit.name" maxlength="64" placeholder="例如：DeepSeek、阿里百炼、OpenAI" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="10">
              <el-form-item label="接口协议">
                <el-select v-model="edit.kind" class="full-width">
                  <el-option value="openai_compatible" label="OpenAI 兼容规范" />
                  <el-option value="anthropic" label="Anthropic 官方协议" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>

          <el-form-item label="接口地址" :required="edit.kind !== 'anthropic'">
            <el-input v-model="edit.base_url" :placeholder="baseUrlPlaceholder" />
          </el-form-item>

          <el-form-item label="API Key" :required="!edit.id">
            <el-input
              v-model="edit.api_key"
              type="password"
              show-password
              :placeholder="edit.id && edit.has_key ? `已加密保存 ${edit.masked}，留空保持不变` : 'sk-...'"
              autocomplete="new-password"
            />
            <div v-if="needsNewKey" class="form-tip warn">{{ KEY_REBIND_TIP }}</div>
          </el-form-item>

          <!-- 可用模型管理区 -->
          <el-form-item label="可用模型" required>
            <div class="models-box">
              <div class="tags-wall">
                <span v-if="!edit.custom_models.length" class="empty-models-hint">
                  暂未选择模型，请从下方推荐模型点选或手动输入添加
                </span>
                <el-tag
                  v-for="m in edit.custom_models"
                  :key="m"
                  closable
                  class="model-tag-pill mono"
                  @close="removeModelTag(m)"
                >
                  {{ m }}
                </el-tag>
                <div class="quick-add-input-box">
                  <el-input
                    v-model="edit.new_model_tag"
                    placeholder="+ 回车自定义模型"
                    size="small"
                    class="quick-input"
                    @keyup.enter="addModelTag"
                  />
                  <el-button size="small" @click="addModelTag">添加</el-button>
                </div>
              </div>

              <!-- 快捷点选预设推荐模型 -->
              <div v-if="suggestedPresetModels.length" class="quick-suggest-section">
                <div class="suggest-header">
                  <span class="suggest-title">推荐常用模型（点击选择）：</span>
                  <div class="suggest-actions">
                    <button type="button" class="link-btn primary" @click="addAllSuggested">全选推荐</button>
                    <button v-if="edit.custom_models.length" type="button" class="link-btn muted" @click="edit.custom_models = []">清空</button>
                  </div>
                </div>
                <div class="suggest-chips">
                  <button
                    v-for="m in suggestedPresetModels"
                    :key="m"
                    type="button"
                    class="model-chip-btn"
                    :class="{ selected: edit.custom_models.includes(m) }"
                    @click="toggleModel(m)"
                  >
                    <span class="chip-icon">{{ edit.custom_models.includes(m) ? '✓' : '+' }}</span>
                    <span class="chip-text mono">{{ m }}</span>
                  </button>
                </div>
              </div>

              <!-- 从接口拉取模型列表操作区 -->
              <div class="model-action-bar">
                <el-button size="small" :icon="Download" :loading="edit.fetching" @click="pullModels">
                  从接口拉取模型列表
                </el-button>
                <span class="action-tip">填写 Key 后可在线查询该服务商所有可用模型</span>
              </div>

              <!-- 在线拉取到的模型列表点选区 -->
              <div v-if="remoteFetchedModels.length" class="remote-models-section">
                <div class="suggest-header">
                  <span class="suggest-title">接口在线返回模型（{{ remoteFetchedModels.length }} 个）：</span>
                  <button type="button" class="link-btn primary" @click="addAllRemote">全选接口模型</button>
                </div>
                <div class="suggest-chips remote-scroll">
                  <button
                    v-for="m in remoteFetchedModels"
                    :key="m"
                    type="button"
                    class="model-chip-btn"
                    :class="{ selected: edit.custom_models.includes(m) }"
                    @click="toggleModel(m)"
                  >
                    <span class="chip-icon">{{ edit.custom_models.includes(m) ? '✓' : '+' }}</span>
                    <span class="chip-text mono">{{ m }}</span>
                  </button>
                </div>
              </div>
            </div>
          </el-form-item>
        </el-form>
      </div>

      <template #footer>
        <div class="dialog-footer-content">
          <el-button :icon="Connection" :loading="edit.testing" @click="probe">测试连通性</el-button>
          <div class="footer-right-buttons">
            <el-button @click="edit.open = false">取消</el-button>
            <el-button type="primary" :loading="edit.saving" @click="save">完成接入并保存</el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* ================= 1. 现代化页面头部 ================= */
.page {
  padding-bottom: 32px;
}

.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 24px;
}

.page-head-left {
  min-width: 0;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 14px;
}

.title-icon-box {
  width: 42px;
  height: 42px;
  border-radius: var(--xh-radius-md, 10px);
  background: var(--xh-primary-soft, #ecfdf5);
  color: var(--xh-primary, #10b981);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  flex-shrink: 0;
}

.title-text-group {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.title-with-pill {
  display: flex;
  align-items: center;
  gap: 12px;
}

.title-with-pill h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--xh-text, #0f172a);
  letter-spacing: -0.2px;
}

.page-subtitle {
  margin: 0;
  font-size: 13px;
  color: var(--xh-muted, #64748b);
  line-height: 1.4;
}

.page-head-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.page-head-right :deep(.el-button + .el-button) {
  margin-left: 0;
}

/* 状态药丸胶囊 */
.gateway-live-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
  background: var(--xh-fill, #f8fafc);
  border: 1px solid var(--xh-border, #e2e8f0);
}

.gateway-live-pill.online {
  color: #059669;
  background: #ecfdf5;
  border-color: rgba(16, 185, 129, 0.25);
}

.gateway-live-pill.offline {
  color: var(--xh-danger, #ef4444);
  background: rgba(239, 68, 68, 0.08);
  border-color: rgba(239, 68, 68, 0.2);
}

/* ================= 2. 业务场景模型调度区块 ================= */
.content-section {
  margin-bottom: 24px;
}

.section-head-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 14px;
}

.section-head-left {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 10px;
}

.section-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-title-icon {
  font-size: 16px;
  color: var(--xh-primary, #10b981);
}

.section-heading {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--xh-text, #0f172a);
}

.section-subtext {
  font-size: 12px;
  color: var(--xh-muted, #64748b);
}

.scenario-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

@media (max-width: 1024px) {
  .scenario-grid {
    grid-template-columns: 1fr;
  }
}

.scenario-card {
  background: var(--xh-card, #ffffff);
  border: 1px solid var(--xh-border, #e2e8f0);
  border-radius: 14px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 220px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03), 0 1px 2px rgba(0, 0, 0, 0.02);
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
}

.scenario-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
  border-color: rgba(16, 185, 129, 0.3);
}

.scenario-card.is-customized {
  border-color: rgba(59, 130, 246, 0.3);
}

.scenario-card-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.scenario-icon-box {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.scenario-icon-box.chat {
  background: #ecfdf5;
  color: #059669;
}

.scenario-icon-box.vision {
  background: #fffbeb;
  color: #d97706;
}

.scenario-icon-box.fast {
  background: #eef2ff;
  color: #4f46e5;
}

.scenario-header-text {
  flex: 1;
  min-width: 0;
}

.scenario-title-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.scenario-name {
  font-weight: 600;
  font-size: 15px;
  color: var(--xh-text, #0f172a);
}

.scenario-role-pill {
  font-size: 11px;
  font-weight: 500;
  padding: 1px 8px;
  border-radius: 12px;
  white-space: nowrap;
}

.scenario-role-pill.chat {
  color: #059669;
  background: #ecfdf5;
}

.scenario-role-pill.vision {
  color: #d97706;
  background: #fffbeb;
}

.scenario-role-pill.fast {
  color: #4f46e5;
  background: #eef2ff;
}

.scenario-desc {
  font-size: 12px;
  color: var(--xh-muted, #64748b);
  margin: 4px 0 0;
  line-height: 1.45;
}

.scenario-selector-block {
  margin: 16px 0 10px;
}

.selector-meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.selector-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--xh-text-2, #475569);
}

.selector-state-pill {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
}

.selector-state-pill.inherit {
  color: var(--xh-muted, #64748b);
  background: var(--xh-fill-strong, #f1f5f9);
}

.selector-state-pill.custom {
  color: #2563eb;
  background: rgba(59, 130, 246, 0.1);
  font-weight: 500;
}

.scenario-card-footer {
  padding-top: 10px;
  border-top: 1px dashed var(--xh-border, #f1f5f9);
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  gap: 8px;
}

.footer-status-indicator {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  overflow: hidden;
}

.footer-model-label {
  color: var(--xh-muted, #94a3b8);
  font-size: 11px;
  flex-shrink: 0;
}

.footer-model-name {
  color: var(--xh-text, #0f172a);
  font-weight: 600;
  font-size: 11.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.footer-right-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.footer-provider-badge {
  color: var(--xh-muted, #64748b);
  background: var(--xh-fill-strong, #f1f5f9);
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 10.5px;
  white-space: nowrap;
  flex-shrink: 0;
}

.pulse-dot-sm {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}

.pulse-dot-sm.green {
  background: #10b981;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2);
}

.pulse-dot-sm.blue {
  background: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}

.footer-warn-inline {
  color: #d97706;
  background: #fffbe6;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  flex-shrink: 0;
}

.save-btn-unsaved {
  animation: pulse-save 2s infinite ease-in-out;
}

@keyframes pulse-save {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.4);
  }
  50% {
    box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.25);
  }
}

/* ================= 3. 网关运行信息指标条 (极简横向数据条) ================= */
.metrics-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--xh-card, #ffffff);
  border: 1px solid var(--xh-border, #e2e8f0);
  border-radius: 12px;
  padding: 14px 24px;
  margin-bottom: 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

@media (max-width: 800px) {
  .metrics-bar {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
  }
  .metric-divider {
    display: none;
  }
}

.metric-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 1;
}

.metric-caption {
  font-size: 12px;
  color: var(--xh-muted, #64748b);
  font-weight: 500;
}

.metric-val-wrap {
  display: flex;
  align-items: baseline;
  gap: 4px;
  min-width: 0;
}

.metric-val-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--xh-text, #0f172a);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric-num-bold {
  font-size: 18px;
  font-weight: 700;
  color: var(--xh-text, #0f172a);
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.metric-sub-unit {
  font-size: 11px;
  color: var(--xh-muted, #64748b);
}

.metric-budget-hint {
  font-size: 11px;
  color: var(--xh-muted, #64748b);
}

.metric-divider {
  width: 1px;
  height: 28px;
  background: var(--xh-border, #e2e8f0);
  margin: 0 16px;
  flex-shrink: 0;
}

.status-live-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  color: #059669;
}

.err-text {
  font-size: 11px;
  color: var(--xh-danger);
}

/* ================= 4. 已接入服务商管理网格 ================= */
.providers-section {
  margin-top: 20px;
}

.section-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
  flex-wrap: wrap;
  gap: 8px;
}

.section-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.section-header-left h3 {
  margin: 0;
  font-size: var(--xh-fs-md);
  font-weight: 600;
  color: var(--xh-text);
}

.section-count-badge {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
  background: var(--xh-fill-strong);
  padding: 2px 8px;
  border-radius: var(--xh-radius-full);
}

.providers-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
}

@media (max-width: 640px) {
  .providers-grid {
    grid-template-columns: 1fr;
  }
}

.provider-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-lg);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-shadow: var(--xh-shadow-sm);
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}

.provider-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--xh-shadow-md);
  border-color: var(--xh-primary-soft);
}

.provider-card.disabled {
  opacity: 0.65;
}

.card-top-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.provider-brand-box {
  width: 44px;
  height: 44px;
  border-radius: var(--xh-radius-md);
  border: 1px solid transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.3px;
  flex-shrink: 0;
}

.provider-info-col {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 0;
}

.provider-name-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.provider-title {
  font-size: var(--xh-fs-base);
  font-weight: 600;
  color: var(--xh-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.provider-sub-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.protocol-badge {
  font-size: 11px;
  color: var(--xh-muted);
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  padding: 1px 6px;
  border-radius: 4px;
}

.active-tiers-list {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.active-tier-pill {
  font-size: 11px;
  color: var(--xh-primary);
  background: var(--xh-primary-soft);
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
}

.provider-switch-wrap {
  flex-shrink: 0;
}

.provider-specs-card {
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.spec-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--xh-fs-xs);
  min-width: 0;
}

.spec-label {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 48px;
  flex-shrink: 0;
  color: var(--xh-muted);
}

.spec-val {
  color: var(--xh-text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.models-row {
  align-items: flex-start;
}

.models-chips-wrap {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  min-width: 0;
}

.model-chip-tag {
  font-size: 11px;
  color: var(--xh-text-2);
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  padding: 1px 6px;
  border-radius: 4px;
}

.more-models-chip {
  font-size: 11px;
  color: var(--xh-muted);
}

.card-bottom-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: auto;
  padding-top: 4px;
}

.health-status-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.health-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--xh-fs-xs);
  font-weight: 500;
}

.health-pill.ok {
  color: var(--xh-primary);
}

.health-pill.fail {
  color: var(--xh-danger);
}

.health-pill.none {
  color: var(--xh-muted);
}

.health-time {
  font-size: 11px;
  color: var(--xh-muted);
}

.health-err-msg {
  font-size: 11px;
  color: var(--xh-danger);
  max-width: 140px;
}

.actions-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.actions-group :deep(.el-button + .el-button) {
  margin-left: 0;
}

/* ================= 6. 脉冲圆点通用动效 ================= */
.pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}

.pulse-dot.green {
  background: #10b981;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2);
}

.pulse-dot.orange {
  background: #f59e0b;
  box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.2);
}

.pulse-dot.blue {
  background: #6366f1;
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
}

.pulse-dot.red {
  background: #ef4444;
  box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.2);
}

.pulse-dot.gray {
  background: #94a3b8;
}

/* ---------- 弹窗：参考新供应商多卡片风格 ---------- */
.dialog-body-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.preset-selection-panel {
  background: #f8fafc;
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.preset-filter-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.panel-section-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--xh-text);
}
.category-tabs {
  display: flex;
  gap: 4px;
  background: #eef2f6;
  padding: 2px;
  border-radius: 6px;
}
.category-tab-btn {
  border: none;
  background: transparent;
  font-size: 12px;
  padding: 3px 8px;
  border-radius: 4px;
  cursor: pointer;
  color: var(--xh-text-muted);
  transition: all 0.15s;
}
.category-tab-btn:hover {
  color: var(--xh-text);
}
.category-tab-btn.active {
  background: #ffffff;
  color: var(--xh-brand);
  font-weight: 500;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.preset-pills-container {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  max-height: 160px;
  overflow-y: auto;
  padding-right: 4px;
}
.preset-pill-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #ffffff;
  border: 1px solid var(--xh-border);
  border-radius: 20px;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 500;
  color: #334155;
  cursor: pointer;
  transition: all 0.15s ease;
  user-select: none;
}
.preset-pill-btn:hover {
  border-color: var(--xh-brand);
  color: var(--xh-brand);
  background: #f0fdf4;
}
.preset-pill-btn.active {
  background: #0284c7;
  border-color: #0284c7;
  color: #ffffff;
  font-weight: 600;
  box-shadow: 0 2px 6px rgba(2, 132, 199, 0.28);
}
.preset-pill-btn.connected:not(.active) {
  border-color: #86efac;
  background: #f0fdf4;
}
.pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #22c55e;
}
.preset-notice-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #475569;
  background: rgba(2, 132, 199, 0.06);
  padding: 6px 12px;
  border-radius: var(--xh-radius-sm);
  line-height: 1.4;
  border-left: 3px solid #0284c7;
}

/* 模型管理区 */
.models-box {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.tags-wall {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  padding: 8px 10px;
  background: #f8fafc;
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-sm);
  min-height: 48px;
  align-items: center;
}
.model-tag-pill {
  font-size: 11px;
}
.quick-add-input-box {
  display: flex;
  gap: 6px;
  align-items: center;
}
.quick-input {
  width: 170px;
}
.model-action-bar {
  display: flex;
  align-items: center;
  gap: 10px;
}
.action-tip {
  font-size: 12px;
  color: var(--xh-text-muted);
}

.empty-models-hint {
  font-size: 12px;
  color: var(--xh-text-muted);
  padding: 4px;
}

.quick-suggest-section,
.remote-models-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: #f8fafc;
  border: 1px dashed var(--xh-border);
  border-radius: var(--xh-radius-sm);
  padding: 8px 10px;
}

.suggest-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.suggest-title {
  font-size: 12px;
  font-weight: 500;
  color: #475569;
}

.suggest-actions {
  display: flex;
  gap: 8px;
}

.link-btn {
  background: none;
  border: none;
  padding: 0;
  font-size: 11px;
  cursor: pointer;
  user-select: none;
}
.link-btn.primary {
  color: var(--xh-brand);
}
.link-btn.primary:hover {
  text-decoration: underline;
}
.link-btn.muted {
  color: #94a3b8;
}
.link-btn.muted:hover {
  color: #64748b;
}

.suggest-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.suggest-chips.remote-scroll {
  max-height: 140px;
  overflow-y: auto;
  padding-right: 4px;
}

.model-chip-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 12px;
  color: #334155;
  cursor: pointer;
  transition: all 0.15s ease;
  user-select: none;
}
.model-chip-btn:hover {
  border-color: #0284c7;
  color: #0284c7;
  background: #f0f9ff;
}
.model-chip-btn.selected {
  background: #0284c7;
  border-color: #0284c7;
  color: #ffffff;
  font-weight: 500;
}
.chip-icon {
  font-weight: 700;
  font-size: 11px;
}

.dialog-footer-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}
.footer-right-buttons {
  display: flex;
  gap: 8px;
}

.form-tip.warn {
  color: var(--el-color-warning);
  font-size: 12px;
  margin-top: 4px;
}
.full-width {
  width: 100% !important;
}
.empty-state-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-lg);
  padding: var(--xh-space-8) var(--xh-space-4);
  display: flex;
  justify-content: center;
}
</style>

<style>
/* ================= 场景模型下拉菜单浮层样式 (Teleported to body) ================= */
.scenario-model-popper {
  border-radius: 10px !important;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.12), 0 4px 12px rgba(15, 23, 42, 0.06) !important;
  border: 1px solid var(--xh-border, #e2e8f0) !important;
  min-width: 320px !important;
}

.scenario-model-popper .el-select-dropdown__list {
  padding: 6px !important;
}

.scenario-model-popper .el-select-group__title {
  font-size: 11px !important;
  font-weight: 600 !important;
  color: var(--xh-muted, #64748b) !important;
  padding: 8px 12px 4px !important;
  border-top: 1px dashed var(--xh-border, #e2e8f0);
  margin-top: 4px;
}

.scenario-model-popper .el-select-group:first-child .el-select-group__title {
  border-top: none;
  margin-top: 0;
}

.scenario-model-popper .el-select-dropdown__item {
  height: 36px !important;
  line-height: 36px !important;
  padding: 0 10px !important;
  border-radius: 6px !important;
  margin: 1px 0 !important;
}

.scenario-model-popper .el-select-dropdown__item.hover,
.scenario-model-popper .el-select-dropdown__item:hover {
  background-color: var(--xh-fill-strong, #f1f5f9) !important;
}

.scenario-model-popper .el-select-dropdown__item.selected {
  background-color: var(--xh-primary-soft, rgba(16, 185, 129, 0.1)) !important;
  color: var(--xh-primary, #10b981) !important;
  font-weight: 600 !important;
}

.scenario-model-popper .model-opt-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  gap: 10px;
}

.scenario-model-popper .model-opt-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  overflow: hidden;
}

.scenario-model-popper .model-bullet {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--xh-border, #cbd5e1);
  flex-shrink: 0;
  transition: all 0.2s ease;
}

.scenario-model-popper .model-bullet.bullet-active {
  background: var(--xh-primary, #10b981);
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.25);
}

.scenario-model-popper .model-name {
  font-size: 13px;
  color: var(--xh-text, #1e293b);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scenario-model-popper .inherit-row {
  color: var(--xh-text, #1e293b);
}

.scenario-model-popper .inherit-icon {
  font-size: 14px;
  color: var(--xh-primary, #10b981);
  flex-shrink: 0;
}

.scenario-model-popper .inherit-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--xh-text, #1e293b);
}

.scenario-model-popper .inherit-desc {
  font-size: 12px;
  color: var(--xh-muted, #64748b);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scenario-model-popper .model-opt-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
  line-height: 18px;
}

.scenario-model-popper .model-opt-badge.badge-success {
  background: rgba(16, 185, 129, 0.1);
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.2);
}

.scenario-model-popper .model-opt-badge.badge-warning {
  background: rgba(245, 158, 11, 0.1);
  color: #d97706;
  border: 1px solid rgba(245, 158, 11, 0.2);
}

.scenario-model-popper .model-opt-badge.badge-info {
  background: rgba(99, 102, 241, 0.08);
  color: #6366f1;
  border: 1px solid rgba(99, 102, 241, 0.2);
}

.scenario-model-popper .model-opt-badge.badge-primary {
  background: rgba(59, 130, 246, 0.08);
  color: #2563eb;
  border: 1px solid rgba(59, 130, 246, 0.2);
}

.scenario-model-popper .model-opt-badge.badge-inherit {
  background: var(--xh-fill-strong, #f1f5f9);
  color: var(--xh-muted, #64748b);
  border: 1px solid var(--xh-border, #e2e8f0);
}
</style>
