<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatDotRound,
  Check,
  Coin,
  Connection,
  Cpu,
  DataLine,
  Delete,
  Download,
  Edit,
  Key,
  Lightning,
  Link,
  Picture,
  Plus,
  Refresh,
  Setting,
  WarningFilled,
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
const tierSaving = ref(false)

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

function getScenarioProviderName(tierKey: 'chat' | 'vision' | 'fast'): string {
  const formVal = tierForm[tierKey]
  if (formVal) {
    const pid = Number(formVal.split(':')[0])
    const p = providers.value.find((x) => x.id === pid)
    if (p) return p.name
  }
  if (status.value?.tiers?.[tierKey]?.provider_id) {
    const pid = status.value.tiers[tierKey].provider_id
    const p = providers.value.find((x) => x.id === pid)
    if (p) return p.name
  }
  return status.value?.gateway.provider || status.value?.active_source || '系统主用'
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
    <!-- 1. 规范页面头部 -->
    <div class="page-head">
      <div class="title-row">
        <el-icon class="title-icon"><Cpu /></el-icon>
        <h2>模型配置</h2>
      </div>
      <div class="toolbar">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新状态</el-button>
        <el-button v-if="auth.isAdmin" type="primary" :icon="Plus" @click="openCreate('deepseek')">添加新服务商</el-button>
      </div>
    </div>

    <!-- 2. 业务场景模型配置 (Top Section) -->
    <el-card shadow="never" class="block config-card">
      <template #header>
        <div class="card-head">
          <div class="card-title-group">
            <el-icon class="title-icon"><Setting /></el-icon>
            <div class="title-text-group">
              <span class="section-title">业务场景模型配置</span>
              <span class="section-hint">按场景灵活挑选生效模型，支持跨服务商任意混搭调度</span>
            </div>
          </div>
          <div class="card-head-extra">
            <span class="gateway-live-pill" :class="status?.gateway.available ? 'online' : 'offline'">
              <span class="pulse-dot" :class="status?.gateway.available ? 'green' : 'red'"></span>
              <span>{{ status?.gateway.available ? '网关运行中' : '网关未就绪' }}</span>
            </span>
            <el-button
              v-if="auth.isAdmin"
              type="primary"
              :icon="Check"
              :loading="tierSaving"
              @click="saveTiers"
            >
              保存模型配置
            </el-button>
          </div>
        </div>
      </template>

      <!-- 场景三列卡片网格 -->
      <div class="scenario-grid">
        <!-- 1. 智能客服问答 -->
        <div class="scenario-card chat-scenario">
          <div class="scenario-header">
            <div class="scenario-icon-title">
              <div class="scenario-icon-box chat">
                <el-icon><ChatDotRound /></el-icon>
              </div>
              <div class="scenario-meta">
                <span class="scenario-name">智能客服问答</span>
                <span class="scenario-slug">BUYER CHAT AGENT</span>
              </div>
            </div>
            <el-tag size="small" type="success" effect="light" round>对话主力 · Chat</el-tag>
          </div>

          <p class="scenario-desc">买家消息实时智能回复、多轮议价谈判与防封打招呼策略</p>

          <div class="active-model-strip">
            <span class="pulse-dot green"></span>
            <span class="strip-label">生效模型：</span>
            <span class="strip-val mono">{{ activeChatModel }}</span>
            <span class="strip-source">{{ getScenarioProviderName('chat') }}</span>
          </div>

          <div class="scenario-select-wrap">
            <label class="select-label">指定模型（可选，默认继承当前服务商）：</label>
            <el-select
              v-model="tierForm.chat"
              :placeholder="`默认继承主服务商（${status?.gateway.models.chat || '未配置'}）`"
              clearable
              class="full-width"
              :disabled="!auth.isAdmin"
            >
              <el-option-group v-for="g in providerModelGroups" :key="g.id" :label="g.name">
                <el-option
                  v-for="m in g.models"
                  :key="m.value"
                  :value="m.value"
                  :label="`${g.name} · ${m.label}`"
                >
                  <div class="model-opt-item">
                    <span class="mono">{{ m.label }}</span>
                    <span class="opt-prov-tag">{{ g.name }}</span>
                  </div>
                </el-option>
              </el-option-group>
            </el-select>
          </div>
        </div>

        <!-- 2. 看图发品与质检 -->
        <div class="scenario-card vision-scenario">
          <div class="scenario-header">
            <div class="scenario-icon-title">
              <div class="scenario-icon-box vision">
                <el-icon><Picture /></el-icon>
              </div>
              <div class="scenario-meta">
                <span class="scenario-name">看图发品与质检</span>
                <span class="scenario-slug">MULTIMODAL VISION</span>
              </div>
            </div>
            <el-tag size="small" type="warning" effect="light" round>多模态视觉 · Vision</el-tag>
          </div>

          <p class="scenario-desc">以图搜款、看图自动提炼规格瑕疵文案与成色评估</p>

          <div class="active-model-strip">
            <span class="pulse-dot orange"></span>
            <span class="strip-label">生效模型：</span>
            <span class="strip-val mono">{{ activeVisionModel }}</span>
            <span class="strip-source">{{ getScenarioProviderName('vision') }}</span>
          </div>

          <div class="scenario-select-wrap">
            <label class="select-label">指定视觉模型（识图必填）：</label>
            <el-select
              v-model="tierForm.vision"
              :placeholder="`默认继承主服务商（${status?.gateway.models.vision || '未配置'}）`"
              clearable
              class="full-width"
              :disabled="!auth.isAdmin"
            >
              <el-option-group v-for="g in visionGroups" :key="g.id" :label="g.name">
                <el-option
                  v-for="m in g.models"
                  :key="m.value"
                  :value="m.value"
                  :label="`${g.name} · ${m.label}`"
                >
                  <div class="model-opt-item">
                    <span class="mono">{{ m.label }}</span>
                    <el-tag size="small" type="warning" effect="light">视觉支持</el-tag>
                  </div>
                </el-option>
              </el-option-group>
            </el-select>
          </div>

          <div v-if="!hasConnectedVisionModel" class="vision-warn-tip">
            <el-icon><WarningFilled /></el-icon>
            <span>提示：DeepSeek 官方暂不提供识图，建议接入阿里百炼、OpenAI 或智谱</span>
          </div>
        </div>

        <!-- 3. 意图分类与快筛 -->
        <div class="scenario-card fast-scenario">
          <div class="scenario-header">
            <div class="scenario-icon-title">
              <div class="scenario-icon-box fast">
                <el-icon><Lightning /></el-icon>
              </div>
              <div class="scenario-meta">
                <span class="scenario-name">意图分类与快筛</span>
                <span class="scenario-slug">ULTRA-FAST ROUTING</span>
              </div>
            </div>
            <el-tag size="small" type="info" effect="light" round>毫秒极速 · Fast</el-tag>
          </div>

          <p class="scenario-desc">买家意图毫秒级分流与转人工规则过滤，低延迟极低成本</p>

          <div class="active-model-strip">
            <span class="pulse-dot blue"></span>
            <span class="strip-label">生效模型：</span>
            <span class="strip-val mono">{{ activeFastModel }}</span>
            <span class="strip-source">{{ getScenarioProviderName('fast') }}</span>
          </div>

          <div class="scenario-select-wrap">
            <label class="select-label">指定快筛模型（追求极低延迟与成本）：</label>
            <el-select
              v-model="tierForm.fast"
              :placeholder="`默认继承主服务商（${status?.gateway.models.fast || '未配置'}）`"
              clearable
              class="full-width"
              :disabled="!auth.isAdmin"
            >
              <el-option-group v-for="g in providerModelGroups" :key="g.id" :label="g.name">
                <el-option
                  v-for="m in g.models"
                  :key="m.value"
                  :value="m.value"
                  :label="`${g.name} · ${m.label}`"
                >
                  <div class="model-opt-item">
                    <span class="mono">{{ m.label }}</span>
                    <span class="opt-prov-tag">{{ g.name }}</span>
                  </div>
                </el-option>
              </el-option-group>
            </el-select>
          </div>
        </div>
      </div>

      <!-- 3. 网关运行信息指标条 (Metrics Strip) -->
      <div v-if="status" class="gateway-metrics-strip">
        <div class="metric-cell">
          <div class="metric-icon-box source">
            <el-icon><Connection /></el-icon>
          </div>
          <div class="metric-info">
            <span class="metric-label">网关生效来源</span>
            <div class="metric-val-wrap">
              <el-tag v-if="status.using_env" size="small" type="warning" effect="light">.env 环境变量</el-tag>
              <span v-else class="metric-val-text font-medium">{{ status.active_source }}</span>
            </div>
          </div>
        </div>

        <div class="metric-cell">
          <div class="metric-icon-box calls">
            <el-icon><DataLine /></el-icon>
          </div>
          <div class="metric-info">
            <span class="metric-label">今日总调用量</span>
            <div class="metric-val-wrap">
              <span class="metric-val-num">{{ status.gateway.usage_today.calls }}</span>
              <span class="metric-unit">次</span>
            </div>
          </div>
        </div>

        <div class="metric-cell">
          <div class="metric-icon-box tokens">
            <el-icon><Coin /></el-icon>
          </div>
          <div class="metric-info">
            <span class="metric-label">Token 消耗统计</span>
            <div class="metric-val-wrap">
              <span class="metric-val-num">{{ tokenUsed.toLocaleString() }}</span>
              <span class="metric-unit">tokens</span>
              <span v-if="status.gateway.usage_today.budget" class="metric-budget">
                / 上限 {{ status.gateway.usage_today.budget.toLocaleString() }}
              </span>
            </div>
          </div>
        </div>

        <div class="metric-cell">
          <div class="metric-icon-box status-ok">
            <el-icon><Check /></el-icon>
          </div>
          <div class="metric-info">
            <span class="metric-label">智能路由状态</span>
            <div class="metric-val-wrap">
              <span class="status-live-pill">
                <span class="pulse-dot green"></span>
                <span>按场景分发中</span>
              </span>
            </div>
          </div>
        </div>

        <div v-if="status.gateway.error" class="metric-cell error">
          <div class="metric-icon-box err">
            <el-icon><WarningFilled /></el-icon>
          </div>
          <div class="metric-info">
            <span class="metric-label">异常告警</span>
            <span class="err-text">{{ status.gateway.error }}</span>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 4. 已接入服务商管理 (Connected Providers List) -->
    <div v-if="auth.isAdmin" class="providers-section">
      <div class="section-header-row">
        <div class="section-header-left">
          <h3>已接入服务商</h3>
          <span class="section-count-badge">{{ providers.length }} 个已配置</span>
        </div>
        <el-button text bg size="small" :icon="Plus" @click="openCreate('deepseek')">
          添加服务商
        </el-button>
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
/* ================= 1. 页面头部 ================= */
.page {
  padding-bottom: 24px;
}

.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--xh-space-3);
  margin-bottom: var(--xh-space-4);
}

.title-row {
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
}

.title-row h2 {
  margin: 0;
  font-size: var(--xh-fs-xl);
  font-weight: 600;
  color: var(--xh-text);
}

.title-icon {
  font-size: var(--xh-fs-xl);
  color: var(--xh-primary);
}

.toolbar {
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
}

.toolbar :deep(.el-button + .el-button) {
  margin-left: 0;
}

.block {
  margin-bottom: 20px;
}

/* ================= 2. 顶部配置卡片 ================= */
.config-card {
  border-radius: var(--xh-radius-lg);
  border: 1px solid var(--xh-border);
  background: var(--xh-card);
  box-shadow: var(--xh-shadow-sm);
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.card-title-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-text-group {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px;
}

.section-title {
  font-size: var(--xh-fs-md);
  font-weight: 600;
  color: var(--xh-text);
}

.section-hint {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}

.card-head-extra {
  display: flex;
  align-items: center;
  gap: 12px;
}

.gateway-live-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: var(--xh-radius-full);
  font-size: var(--xh-fs-xs);
  font-weight: 500;
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
}

.gateway-live-pill.online {
  color: var(--xh-primary);
  background: var(--xh-primary-soft);
  border-color: rgba(16, 185, 129, 0.25);
}

.gateway-live-pill.offline {
  color: var(--xh-danger);
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.2);
}

/* ================= 3. 场景卡片网格 ================= */
.scenario-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}

@media (max-width: 960px) {
  .scenario-grid {
    grid-template-columns: 1fr;
  }
}

.scenario-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-lg);
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-shadow: var(--xh-shadow-sm);
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.2s ease, border-color 0.2s ease;
  position: relative;
  overflow: hidden;
}

.scenario-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--xh-shadow-md);
}

.scenario-card.chat-scenario {
  border-top: 3px solid var(--xh-primary);
}

.scenario-card.vision-scenario {
  border-top: 3px solid #f59e0b;
}

.scenario-card.fast-scenario {
  border-top: 3px solid #6366f1;
}

.scenario-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.scenario-icon-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.scenario-icon-box {
  width: 36px;
  height: 36px;
  border-radius: var(--xh-radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.scenario-icon-box.chat {
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
}

.scenario-icon-box.vision {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
}

.scenario-icon-box.fast {
  background: rgba(99, 102, 241, 0.12);
  color: #6366f1;
}

.scenario-meta {
  display: flex;
  flex-direction: column;
}

.scenario-name {
  font-weight: 600;
  font-size: var(--xh-fs-base);
  color: var(--xh-text);
  line-height: 1.3;
}

.scenario-slug {
  font-size: 10px;
  font-weight: 600;
  color: var(--xh-muted);
  letter-spacing: 0.5px;
}

.scenario-desc {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
  margin: 0;
  line-height: 1.45;
  min-height: 34px;
}

/* 生效模型条 */
.active-model-strip {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-sm);
  padding: 6px 10px;
  font-size: var(--xh-fs-xs);
}

.strip-label {
  color: var(--xh-muted);
  flex-shrink: 0;
}

.strip-val {
  font-weight: 600;
  color: var(--xh-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.strip-source {
  margin-left: auto;
  font-size: 11px;
  color: var(--xh-muted);
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  padding: 1px 6px;
  border-radius: 4px;
  white-space: nowrap;
}

.scenario-select-wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: auto;
}

.select-label {
  font-size: var(--xh-fs-xs);
  font-weight: 500;
  color: var(--xh-text-2);
}

.vision-warn-tip {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #fffbe6;
  border: 1px solid #ffe58f;
  padding: 6px 10px;
  border-radius: var(--xh-radius-sm);
  font-size: 11px;
  color: #d46b08;
  line-height: 1.3;
}

.model-opt-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.opt-prov-tag {
  font-size: 11px;
  color: var(--xh-muted);
  background: var(--xh-fill-strong);
  padding: 1px 6px;
  border-radius: 4px;
}

/* ================= 4. 网关统计指标条 ================= */
.gateway-metrics-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 14px 16px;
  background: var(--xh-fill);
  border-radius: var(--xh-radius-md);
  border: 1px solid var(--xh-border);
}

@media (max-width: 900px) {
  .gateway-metrics-strip {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 600px) {
  .gateway-metrics-strip {
    grid-template-columns: 1fr;
  }
}

.metric-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.metric-icon-box {
  width: 32px;
  height: 32px;
  border-radius: var(--xh-radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}

.metric-icon-box.source {
  background: rgba(16, 185, 129, 0.12);
  color: var(--xh-primary);
}

.metric-icon-box.calls {
  background: rgba(59, 130, 246, 0.12);
  color: #3b82f6;
}

.metric-icon-box.tokens {
  background: rgba(245, 158, 11, 0.12);
  color: #f59e0b;
}

.metric-icon-box.status-ok {
  background: rgba(16, 185, 129, 0.12);
  color: var(--xh-primary);
}

.metric-icon-box.err {
  background: rgba(239, 68, 68, 0.12);
  color: var(--xh-danger);
}

.metric-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.metric-label {
  font-size: 11px;
  color: var(--xh-muted);
}

.metric-val-wrap {
  display: flex;
  align-items: baseline;
  gap: 4px;
  min-width: 0;
}

.metric-val-num {
  font-size: var(--xh-fs-md);
  font-weight: 700;
  color: var(--xh-text);
  line-height: 1.2;
}

.metric-val-text {
  font-size: var(--xh-fs-xs);
  font-weight: 600;
  color: var(--xh-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric-unit {
  font-size: 11px;
  color: var(--xh-muted);
}

.metric-budget {
  font-size: 11px;
  color: var(--xh-muted);
}

.status-live-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--xh-fs-xs);
  font-weight: 500;
  color: var(--xh-primary);
}

.err-text {
  font-size: 11px;
  color: var(--xh-danger);
}

/* ================= 5. 已接入服务商管理网格 ================= */
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
