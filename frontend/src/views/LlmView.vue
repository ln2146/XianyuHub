<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatLineRound,
  Check,
  Connection,
  Delete,
  Download,
  InfoFilled,
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

// 常用推荐预设
const popularPresetIds = ['deepseek', 'dashscope', 'zhipu', 'moonshot', 'siliconflow']
const popularPresets = computed(() =>
  presets.value.filter((p) => popularPresetIds.includes(p.id)),
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
        isVision: /vl|vision|4v|gemini|image/i.test(m) || m === p.model_vision,
      })),
    }
  })
})

const visionGroups = computed(() => {
  return providerModelGroups.value
    .map((g) => ({
      ...g,
      models: g.models.filter((m) => m.isVision || g.name.includes('阿里') || g.name.includes('智谱')),
    }))
    .filter((g) => g.models.length > 0)
})

const hasConnectedVisionModel = computed(() => {
  return enabledProviders.value.some(
    (p) => p.model_vision || getProviderModels(p).some((m) => /vl|vision|4v|image/i.test(m)),
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
  show_advanced: false,
})

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

const baseUrlPlaceholder = computed(() => {
  if (edit.preset === 'dashscope') return '例如 https://dashscope.aliyuncs.com/compatible-mode/v1'
  if (edit.preset === 'deepseek') return '例如 https://api.deepseek.com/v1'
  if (edit.preset === 'zhipu') return '例如 https://open.bigmodel.cn/api/paas/v4'
  if (edit.preset === 'moonshot') return '例如 https://api.moonshot.cn/v1'
  if (edit.preset === 'siliconflow') return '例如 https://api.siliconflow.cn/v1'
  return '例如 https://dashscope.aliyuncs.com/compatible-mode/v1 或 https://api.deepseek.com/v1'
})

function applyPreset(id: string) {
  const p = presets.value.find((x) => x.id === id)
  if (!p) return
  edit.kind = (p.kind || 'openai_compatible') as LlmKind
  edit.base_url = p.base_url
  edit.model_vision = p.models.vision
  edit.model_chat = p.models.chat
  edit.model_fast = p.models.fast
  if (!edit.id) {
    edit.name = p.name === '自定义' ? '' : p.name
  }
  const suggested = p.suggested_models || []
  const initial = [p.models.chat, p.models.vision, p.models.fast, ...suggested].filter(Boolean)
  edit.custom_models = Array.from(new Set(initial))
}

function openCreate(presetId = 'deepseek') {
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
    show_advanced: false,
  })
  applyPreset(presetId)
}

function openEdit(p: LlmProvider) {
  const presetMatch = presets.value.find((x) => x.name === p.name || x.base_url === p.base_url)
  const allModels = getProviderModels(p)

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
    show_advanced: false,
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
  return {
    name: edit.name.trim(),
    kind: edit.kind,
    base_url: edit.base_url.trim(),
    api_key: edit.api_key,
    model_vision: edit.model_vision.trim() || (edit.custom_models.find((m) => /vl|vision|4v|image/i.test(m)) || ''),
    model_chat: edit.model_chat.trim() || edit.custom_models[0] || '',
    model_fast: edit.model_fast.trim() || edit.custom_models[0] || '',
    custom_models: edit.custom_models,
    timeout_seconds: edit.timeout_seconds,
    anthropic_fallbacks: edit.anthropic_fallbacks,
    daily_token_budget: edit.daily_token_budget,
  }
}

function validate(): boolean {
  if (!edit.name.trim()) {
    ElMessage.warning('请填写服务商名称')
    return false
  }
  if (!edit.base_url.trim()) {
    ElMessage.warning('请填写接口地址')
    return false
  }
  if (!edit.id && !edit.api_key.trim()) {
    ElMessage.warning('请填写 API Key')
    return false
  }
  if (!edit.custom_models.length && !edit.model_chat.trim() && !edit.model_fast.trim()) {
    ElMessage.warning('请至少添加一个可用模型')
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
  if (!edit.base_url.trim()) return ElMessage.warning('请先填写接口地址')
  if (needsNewKey.value) return ElMessage.warning(KEY_REBIND_TIP)
  edit.fetching = true
  try {
    const r = await fetchLlmModels({ ...payload(), id: edit.id ?? undefined })
    if (r.models.length) {
      const merged = new Set([...edit.custom_models, ...r.models])
      edit.custom_models = Array.from(merged)
      ElMessage.success(`拉取成功！已同步 ${r.models.length} 个可用模型`)
    } else {
      ElMessage.warning('接口未返回可用模型列表，请手动添加模型名')
    }
  } catch (e) {
    ElMessage.error(errorMessage(e))
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
        <span class="page-subtitle">一键接入国内外大模型服务商，自由分派客服问答、识图发品与意图识别场景</span>
      </div>
      <div class="toolbar">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新状态</el-button>
        <el-button v-if="auth.isAdmin" type="primary" :icon="Plus" @click="openCreate('custom')">自定义接入</el-button>
      </div>
    </div>

    <!-- 1. 业务场景模型配置 (Top Card) -->
    <el-card shadow="never" class="block config-card">
      <template #header>
        <div class="card-head">
          <div class="card-title-group">
            <el-icon class="title-icon"><Setting /></el-icon>
            <span class="section-title">业务场景模型配置</span>
            <span class="section-hint">按场景灵活选用已配置的模型，支持跨供应商混合调度</span>
          </div>
          <div class="card-head-extra">
            <el-tag :type="status?.gateway.available ? 'success' : 'danger'" size="small" effect="dark">
              {{ status?.gateway.available ? '● 网关运行中' : '● 网关不可用' }}
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
              placeholder="选择支持视觉的模型"
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
            <span>提示：DeepSeek 暂不提供识图模型，建议接入阿里百炼（通义千问）或智谱</span>
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
          <p class="scenario-desc">买家消息意图毫秒级识别与规则前置粗筛，极低延迟与成本</p>
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
          <span class="stat-label">配置来源：</span>
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

    <!-- 2. 一键快速接入推荐 (Quick Connect Cards) -->
    <div v-if="auth.isAdmin" class="quick-connect-section">
      <div class="section-header-row">
        <div class="title-with-badge">
          <span class="quick-badge">快捷接入</span>
          <h3 class="quick-title">一键接入主流大模型</h3>
        </div>
        <span class="quick-sub">点击即可直接载入预设，仅需粘贴 API Key 即可快速连通</span>
      </div>

      <div class="quick-grid">
        <div
          v-for="p in popularPresets"
          :key="p.id"
          class="quick-card"
          :class="{ connected: isPresetConnected(p.name) }"
          @click="openCreate(p.id)"
        >
          <div class="quick-card-top">
            <span class="quick-card-name">{{ p.name }}</span>
            <el-tag v-if="isPresetConnected(p.name)" size="small" type="success" effect="light">已接入</el-tag>
            <el-button v-else size="small" type="primary" plain :icon="Plus">一键接入</el-button>
          </div>
          <p class="quick-card-note">{{ p.note }}</p>
          <div class="quick-card-models">
            <span v-for="m in (p.suggested_models || []).slice(0, 3)" :key="m" class="model-chip">
              {{ m }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 3. 已接入服务商管理 (Connected Providers List) -->
    <div v-if="auth.isAdmin" class="providers-section">
      <div class="section-header-row">
        <h3>已接入服务商 ({{ providers.length }})</h3>
        <el-button type="primary" plain :icon="Plus" size="small" @click="openCreate('custom')">
          添加其他服务商
        </el-button>
      </div>

      <div v-if="!loading && !providers.length" class="empty-state-card">
        <el-empty description="尚未接入大模型服务商，点击上方「一键接入」即可开启智能功能">
          <el-button type="primary" :icon="Plus" @click="openCreate('deepseek')">立即接入 DeepSeek</el-button>
        </el-empty>
      </div>

      <div v-else class="grid">
        <el-card v-for="p in providers" :key="p.id" shadow="never" class="prov" :class="{ disabled: !p.enabled }">
          <div class="prov-head">
            <div class="prov-title-wrap">
              <span class="prov-name">{{ p.name }}</span>
              <el-tag v-if="!p.enabled" size="small" type="info" class="ml">已停用</el-tag>
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
              <span class="muted small">接口</span>
              <span class="mono small ellipsis">{{ p.base_url || '默认官方地址' }}</span>
            </div>
            <div class="row">
              <span class="muted small">Key</span>
              <span class="mono small">{{ p.api_key_masked || '未填写' }}</span>
            </div>
            <div class="row">
              <span class="muted small">模型</span>
              <div class="models-tag-wrap ellipsis">
                <span v-for="m in getProviderModels(p).slice(0, 4)" :key="m" class="small-tag mono">
                  {{ m }}
                </span>
                <span v-if="getProviderModels(p).length > 4" class="small muted">
                  +{{ getProviderModels(p).length - 4 }}
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
              <el-tag size="small" type="danger" effect="plain">测试失败</el-tag>
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

    <!-- 4. 接入 / 编辑服务商模态框 (Simplified Modal) -->
    <el-dialog
      v-model="edit.open"
      :title="edit.id ? `编辑接入 · ${edit.name}` : `接入大模型服务商 · ${activePreset?.name || '自定义'}`"
      :width="isMobile ? '94%' : '600px'"
      :close-on-click-modal="false"
      class="model-dialog"
    >
      <el-form label-width="100px" :label-position="isMobile ? 'top' : 'right'" class="model-form">
        <el-form-item v-if="!edit.id" label="服务商预设">
          <div class="preset-field-wrap">
            <el-select v-model="edit.preset" class="full-width" placeholder="选择预设" @change="applyPreset">
              <el-option v-for="p in presets" :key="p.id" :value="p.id" :label="p.name">
                <div class="preset-option-row">
                  <span class="preset-option-name">{{ p.name }}</span>
                  <span v-if="p.note" class="preset-option-note">{{ p.note }}</span>
                </div>
              </el-option>
            </el-select>
            <div v-if="activePreset?.note" class="preset-hint">
              <el-icon class="preset-hint-icon"><InfoFilled /></el-icon>
              <span>{{ activePreset.note }}</span>
            </div>
          </div>
        </el-form-item>

        <el-form-item label="服务商名称" required>
          <el-input v-model="edit.name" maxlength="64" placeholder="例如：DeepSeek、阿里百炼" />
        </el-form-item>

        <el-form-item label="接口地址" required>
          <el-input v-model="edit.base_url" :placeholder="baseUrlPlaceholder" />
        </el-form-item>

        <el-form-item label="API Key" :required="!edit.id">
          <el-input
            v-model="edit.api_key"
            type="password"
            show-password
            :placeholder="edit.id && edit.has_key ? `已保存 ${edit.masked}，留空保持不变` : 'sk-...'"
            autocomplete="new-password"
          />
          <div v-if="needsNewKey" class="form-tip warn">{{ KEY_REBIND_TIP }}</div>
        </el-form-item>

        <!-- 可用模型管理 -->
        <el-form-item label="可用模型">
          <div class="models-manager">
            <div class="tags-container">
              <el-tag
                v-for="m in edit.custom_models"
                :key="m"
                closable
                class="model-tag"
                @close="removeModelTag(m)"
              >
                {{ m }}
              </el-tag>
              <div class="add-model-input-wrap">
                <el-input
                  v-model="edit.new_model_tag"
                  placeholder="+ 手动添加模型名按回车"
                  size="small"
                  class="add-model-input"
                  @keyup.enter="addModelTag"
                />
                <el-button size="small" @click="addModelTag">添加</el-button>
              </div>
            </div>

            <div class="model-pull-bar">
              <el-button size="small" :icon="Download" :loading="edit.fetching" @click="pullModels">
                从接口拉取可用模型
              </el-button>
              <span class="pull-tip">填入 Key 后可在线查询该服务商所有可用模型</span>
            </div>
          </div>
        </el-form-item>

        <!-- 折叠高级选项 -->
        <div class="advanced-toggle" @click="edit.show_advanced = !edit.show_advanced">
          <span>{{ edit.show_advanced ? '收起高级设置' : '展开高级设置（超时与预算）' }}</span>
        </div>

        <template v-if="edit.show_advanced">
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item label="超时时间">
                <el-input-number
                  v-model="edit.timeout_seconds"
                  :min="5"
                  :max="600"
                  :step="5"
                  controls-position="right"
                  class="full-width"
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="Token 预算">
                <el-input-number
                  v-model="edit.daily_token_budget"
                  :min="0"
                  :step="100000"
                  controls-position="right"
                  placeholder="留空沿用全局"
                  class="full-width"
                />
              </el-form-item>
            </el-col>
          </el-row>
        </template>
      </el-form>

      <template #footer>
        <div class="dialog-footer-content">
          <el-button :icon="Connection" :loading="edit.testing" @click="probe">测试连接</el-button>
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
  margin-bottom: 18px;
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

/* 快捷接入推荐 */
.quick-connect-section {
  margin-bottom: 24px;
}
.section-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 8px;
}
.title-with-badge {
  display: flex;
  align-items: center;
  gap: 8px;
}
.quick-badge {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 12px;
}
.quick-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}
.quick-sub {
  font-size: 12px;
  color: var(--xh-text-muted);
}
.quick-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.quick-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: 12px 14px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.quick-card:hover {
  border-color: var(--xh-brand);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}
.quick-card.connected {
  border-color: var(--el-color-success-light-5);
  background: #f6ffed;
}
.quick-card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.quick-card-name {
  font-weight: 600;
  font-size: 14px;
  color: var(--xh-text);
}
.quick-card-note {
  font-size: 12px;
  color: var(--xh-text-muted);
  margin: 0;
  line-height: 1.3;
}
.quick-card-models {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 4px;
}
.model-chip {
  font-size: 10px;
  background: rgba(0, 0, 0, 0.04);
  padding: 1px 6px;
  border-radius: 4px;
  color: var(--xh-text-muted);
}

/* 已接入服务商列表 */
.providers-section {
  margin-bottom: 24px;
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

/* 弹窗与模型管理 */
.full-width {
  width: 100% !important;
}
.preset-field-wrap {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.preset-option-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  gap: 16px;
}
.preset-option-name {
  font-weight: 500;
  color: var(--xh-text);
}
.preset-option-note {
  font-size: 12px;
  color: var(--xh-text-muted);
}
.preset-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--xh-text-muted);
  background: #f4f8fa;
  padding: 6px 12px;
  border-radius: var(--xh-radius-sm);
  line-height: 1.4;
  border-left: 3px solid var(--xh-brand);
}
.preset-hint-icon {
  color: var(--xh-brand);
}

.models-manager {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.tags-container {
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
.model-tag {
  font-family: monospace;
}
.add-model-input-wrap {
  display: flex;
  gap: 6px;
  align-items: center;
}
.add-model-input {
  width: 180px;
}
.model-pull-bar {
  display: flex;
  align-items: center;
  gap: 10px;
}
.pull-tip {
  font-size: 12px;
  color: var(--xh-text-muted);
}
.advanced-toggle {
  text-align: center;
  font-size: 12px;
  color: var(--xh-brand);
  cursor: pointer;
  padding: 8px 0;
  user-select: none;
}
.advanced-toggle:hover {
  text-decoration: underline;
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
.empty-state-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-lg);
  padding: var(--xh-space-8) var(--xh-space-4);
  display: flex;
  justify-content: center;
}
</style>
