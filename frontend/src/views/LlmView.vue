<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatLineRound,
  Check,
  Connection,
  Delete,
  Download,
  Lightning,
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
    <div class="page-head">
      <div>
        <h2>模型配置</h2>
        <span class="page-subtitle">接入主流大模型服务商，自由分派客服问答、识图发品与意图识别场景</span>
      </div>
      <div class="toolbar">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新状态</el-button>
        <el-button v-if="auth.isAdmin" type="primary" :icon="Plus" @click="openCreate('deepseek')">添加新服务商</el-button>
      </div>
    </div>

    <!-- 1. 业务场景模型配置 (Top Section) -->
    <el-card shadow="never" class="block config-card">
      <template #header>
        <div class="card-head">
          <div class="card-title-group">
            <el-icon class="title-icon"><Setting /></el-icon>
            <span class="section-title">业务场景模型配置</span>
            <span class="section-hint">按业务场景灵活挑选生效模型，支持跨服务商任意混搭</span>
          </div>
          <div class="card-head-extra">
            <el-tag :type="status?.gateway.available ? 'success' : 'danger'" size="small" effect="dark">
              {{ status?.gateway.available ? '● 网关运行中' : '● 网关未就绪' }}
            </el-tag>
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

      <div class="scenario-grid">
        <!-- 客服问答 -->
        <div class="scenario-card">
          <div class="scenario-badge-row">
            <div class="badge-icon-title">
              <el-icon class="scenario-icon chat"><ChatLineRound /></el-icon>
              <span class="scenario-name">智能客服问答</span>
            </div>
            <el-tag size="small" type="primary" effect="plain">对话主力 · Chat</el-tag>
          </div>
          <p class="scenario-desc">买家消息自动问答、多轮议价谈判与防封打招呼</p>
          <div class="scenario-select-wrap">
            <span class="select-label">选用模型：</span>
            <el-select
              v-model="tierForm.chat"
              placeholder="选择已接入的模型"
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
                    <span>{{ m.label }}</span>
                    <span class="opt-prov-tag">{{ g.name }}</span>
                  </div>
                </el-option>
              </el-option-group>
            </el-select>
          </div>
          <div class="scenario-footer">
            <span class="cur-label">当前生效：</span>
            <span class="cur-val mono">{{ status?.gateway.models.chat || '未配置' }}</span>
          </div>
        </div>

        <!-- 看图发品 -->
        <div class="scenario-card">
          <div class="scenario-badge-row">
            <div class="badge-icon-title">
              <el-icon class="scenario-icon vision"><Picture /></el-icon>
              <span class="scenario-name">看图发品与质检</span>
            </div>
            <el-tag size="small" type="warning" effect="plain">多模态视觉 · Vision</el-tag>
          </div>
          <p class="scenario-desc">以图搜款、看图写标题文案及成色瑕疵自动化评估</p>
          <div class="scenario-select-wrap">
            <span class="select-label">选用模型：</span>
            <el-select
              v-model="tierForm.vision"
              placeholder="选择支持识图的视觉模型"
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
                    <span>{{ m.label }}</span>
                    <el-tag size="small" type="warning" effect="light">视觉支持</el-tag>
                  </div>
                </el-option>
              </el-option-group>
            </el-select>
          </div>
          <div v-if="!hasConnectedVisionModel" class="vision-warn-tip">
            <el-icon><WarningFilled /></el-icon>
            <span>提示：DeepSeek 暂不提供识图模型，推荐接入阿里百炼、OpenAI 或智谱</span>
          </div>
          <div class="scenario-footer">
            <span class="cur-label">当前生效：</span>
            <span class="cur-val mono">{{ status?.gateway.models.vision || '未配置' }}</span>
          </div>
        </div>

        <!-- 意图识别 -->
        <div class="scenario-card">
          <div class="scenario-badge-row">
            <div class="badge-icon-title">
              <el-icon class="scenario-icon fast"><Lightning /></el-icon>
              <span class="scenario-name">意图分类与快筛</span>
            </div>
            <el-tag size="small" type="info" effect="plain">快速轻量 · Fast</el-tag>
          </div>
          <p class="scenario-desc">买家消息意图毫秒级识别与规则前置粗筛，追求极低延迟与成本</p>
          <div class="scenario-select-wrap">
            <span class="select-label">选用模型：</span>
            <el-select
              v-model="tierForm.fast"
              placeholder="选择轻量高速模型"
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
                    <span>{{ m.label }}</span>
                    <span class="opt-prov-tag">{{ g.name }}</span>
                  </div>
                </el-option>
              </el-option-group>
            </el-select>
          </div>
          <div class="scenario-footer">
            <span class="cur-label">当前生效：</span>
            <span class="cur-val mono">{{ status?.gateway.models.fast || '未配置' }}</span>
          </div>
        </div>
      </div>

      <!-- 网关运行信息条 -->
      <div v-if="status" class="gateway-stats-bar">
        <div class="stat-item">
          <span class="stat-label">生效来源：</span>
          <el-tag v-if="status.using_env" size="small" type="warning">.env 环境变量</el-tag>
          <el-tag v-else size="small" type="success">{{ status.active_source }}</el-tag>
        </div>
        <div class="stat-item">
          <span class="stat-label">今日调用：</span>
          <span class="stat-num">{{ status.gateway.usage_today.calls }} 次</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">今日 Token：</span>
          <span class="stat-num">{{ tokenUsed.toLocaleString() }} tokens</span>
          <span v-if="status.gateway.usage_today.budget" class="muted small">
            （预算上限 {{ status.gateway.usage_today.budget.toLocaleString() }}）
          </span>
        </div>
        <div v-if="status.gateway.error" class="stat-error">
          <el-icon><WarningFilled /></el-icon>
          <span>{{ status.gateway.error }}</span>
        </div>
      </div>
    </el-card>

    <!-- 2. 已接入服务商管理 (Connected Providers List) -->
    <div v-if="auth.isAdmin" class="providers-section">
      <div class="section-header-row">
        <div class="section-header-left">
          <h3>已接入服务商</h3>
          <span class="section-count-badge">{{ providers.length }} 个已配置</span>
        </div>
        <el-button type="primary" :icon="Plus" size="default" @click="openCreate('deepseek')">
          添加新服务商
        </el-button>
      </div>

      <div v-if="!loading && !providers.length" class="empty-state-card">
        <el-empty description="尚未接入大模型服务商，点击上方「添加新服务商」自由选用 OpenAI、Claude、DeepSeek、阿里等厂商">
          <el-button type="primary" :icon="Plus" @click="openCreate('deepseek')">立即添加服务商</el-button>
        </el-empty>
      </div>

      <div v-else class="grid">
        <el-card v-for="p in providers" :key="p.id" shadow="never" class="prov" :class="{ disabled: !p.enabled }">
          <div class="prov-head">
            <div class="prov-title-wrap">
              <div class="prov-name-row">
                <span class="prov-name">{{ p.name }}</span>
                <el-tag v-if="!p.enabled" size="small" type="info" class="ml">已停用</el-tag>
              </div>
              <div v-if="p.active_tiers && p.active_tiers.length" class="prov-tier-tags">
                <el-tag v-for="t in p.active_tiers" :key="t" size="small" type="success" effect="plain">
                  {{ tierLabels[t] || t }}
                </el-tag>
              </div>
            </div>
            <el-switch :model-value="p.enabled" @change="(v: string | number | boolean) => toggle(p, !!v)" />
          </div>

          <div class="prov-body">
            <div class="row">
              <span class="muted small">端点</span>
              <span class="mono small ellipsis">{{ p.base_url || '官方原生端点' }}</span>
            </div>
            <div class="row">
              <span class="muted small">Key</span>
              <span class="mono small">{{ p.api_key_masked || '未填写' }}</span>
            </div>
            <div class="row">
              <span class="muted small">模型</span>
              <div class="models-tag-wrap ellipsis">
                <span v-for="m in getProviderModels(p).slice(0, 5)" :key="m" class="small-tag mono">
                  {{ m }}
                </span>
                <span v-if="getProviderModels(p).length > 5" class="small muted">
                  +{{ getProviderModels(p).length - 5 }}
                </span>
              </div>
            </div>
          </div>

          <div class="prov-test small">
            <template v-if="p.last_test_ok === true">
              <el-tag size="small" type="success" effect="plain">连通正常</el-tag>
              <span class="muted">{{ fmtTime(p.last_test_at) }}</span>
            </template>
            <template v-else-if="p.last_test_ok === false">
              <el-tag size="small" type="danger" effect="plain">连通失败</el-tag>
              <span class="muted ellipsis" :title="p.last_error || ''">{{ p.last_error }}</span>
            </template>
            <span v-else class="muted">尚未进行连通性测试</span>
          </div>

          <div class="prov-ops">
            <el-button size="small" :icon="Connection" :loading="busy[`t-${p.id}`]" @click="test(p)">测试</el-button>
            <el-button size="small" @click="openEdit(p)">编辑</el-button>
            <el-button size="small" type="danger" plain :icon="Delete" @click="remove(p)">删除</el-button>
          </div>
        </el-card>
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
.page {
  padding-bottom: 24px;
}
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}
.page-subtitle {
  font-size: 13px;
  color: var(--xh-text-muted);
  margin-top: 4px;
  display: block;
}
.block {
  margin-bottom: 20px;
}

/* 顶部配置卡片 */
.config-card {
  border-radius: var(--xh-radius-lg);
  border: 1px solid var(--xh-border);
  background: var(--xh-card);
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
  gap: 8px;
}
.title-icon {
  font-size: 18px;
  color: var(--xh-brand);
}
.section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--xh-text);
}
.section-hint {
  font-size: 12px;
  color: var(--xh-text-muted);
  margin-left: 6px;
}
.card-head-extra {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* 场景三列网格 */
.scenario-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}
@media (max-width: 900px) {
  .scenario-grid {
    grid-template-columns: 1fr;
  }
}
.scenario-card {
  background: #fcfdfe;
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: box-shadow 0.2s, border-color 0.2s;
}
.scenario-card:hover {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
.scenario-badge-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.badge-icon-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.scenario-icon {
  font-size: 18px;
  border-radius: 6px;
  padding: 4px;
}
.scenario-icon.chat {
  background: #ecf5ff;
  color: var(--el-color-primary);
}
.scenario-icon.vision {
  background: #fdf6ec;
  color: var(--el-color-warning);
}
.scenario-icon.fast {
  background: #f4f4f5;
  color: #606266;
}
.scenario-name {
  font-weight: 600;
  font-size: 14px;
  color: var(--xh-text);
}
.scenario-desc {
  font-size: 12px;
  color: var(--xh-text-muted);
  margin: 0;
  line-height: 1.4;
  min-height: 34px;
}
.scenario-select-wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.select-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--xh-text);
}
.scenario-footer {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-top: auto;
  font-size: 12px;
  padding-top: 8px;
  border-top: 1px dashed var(--xh-border);
}
.cur-label {
  color: var(--xh-text-muted);
}
.cur-val {
  color: var(--xh-brand);
  font-weight: 500;
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
  color: var(--xh-text-muted);
  background: #f0f2f5;
  padding: 1px 6px;
  border-radius: 4px;
}

/* 网关状态条 */
.gateway-stats-bar {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
  padding: 10px 14px;
  background: var(--xh-fill);
  border-radius: var(--xh-radius-sm);
  border: 1px solid var(--xh-border);
  font-size: 12px;
}
.stat-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.stat-label {
  color: var(--xh-text-muted);
}
.stat-num {
  font-weight: 600;
  color: var(--xh-text);
}
.stat-error {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--el-color-danger);
  margin-left: auto;
}

/* 服务商管理区 */
.providers-section {
  margin-top: 12px;
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
  font-size: 16px;
  font-weight: 600;
}
.section-count-badge {
  font-size: 12px;
  color: var(--xh-text-muted);
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 10px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
}
.prov :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
}
.prov.disabled {
  opacity: 0.65;
}
.prov-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.prov-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.prov-name-row {
  display: flex;
  align-items: center;
}
.prov-name {
  font-weight: 600;
  font-size: 15px;
  color: var(--xh-text);
}
.prov-tier-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.prov-body {
  background: var(--xh-fill);
  border-radius: var(--xh-radius-sm);
  border: 1px solid var(--xh-border);
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.row {
  display: flex;
  gap: 8px;
  min-width: 0;
}
.row > span:first-child {
  flex: 0 0 36px;
}
.models-tag-wrap {
  display: flex;
  gap: 4px;
  align-items: center;
  flex-wrap: wrap;
}
.small-tag {
  font-size: 11px;
  background: #eef2f6;
  padding: 1px 6px;
  border-radius: 4px;
  color: #334155;
}
.prov-test {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.prov-ops {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: auto;
  padding-top: 6px;
}
.prov-ops .el-button + .el-button {
  margin-left: 0;
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
