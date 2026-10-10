<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, Delete, Plus, Refresh } from '@element-plus/icons-vue'
import {
  activateLlmProvider,
  createLlmProvider,
  deleteLlmProvider,
  fetchLlmModels,
  getLlmMeta,
  getLlmStatus,
  listLlmProviders,
  testLlmProvider,
  updateLlmProvider,
  type LlmKind,
  type LlmPreset,
  type LlmProvider,
  type LlmStatus,
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


const tierLabels: Record<string, string> = {
  vision: '多模态判定 / 文案',
  chat: '客服回复',
  fast: '意图分类 / 粗筛',
}

const tokenUsed = computed(() =>
  status.value ? status.value.gateway.usage_today.input_tokens + status.value.gateway.usage_today.output_tokens : 0,
)

async function load() {
  loading.value = true
  try {
    status.value = await getLlmStatus()
    if (auth.isAdmin) {
      const [meta, list] = await Promise.all([getLlmMeta(), listLlmProviders()])
      presets.value = meta.presets
      providers.value = list
    }
  } finally {
    loading.value = false
  }
}
onMounted(load)

// ---------------------------------------------------------------- 编辑
const edit = reactive({
  open: false,
  saving: false,
  testing: false,
  fetching: false,
  id: null as number | null,
  preset: 'custom',
  name: '',
  kind: 'openai_compatible' as LlmKind,
  base_url: '',
  api_key: '',
  model_vision: '',
  model_chat: '',
  model_fast: '',
  timeout_seconds: 90,
  anthropic_fallbacks: true,
  daily_token_budget: null as number | null,
  enabled: true,
  activate: true,
  /** 已保存的 Key 打码值，用于提示“留空保持不变” */
  masked: '',
  has_key: false,
  /** 打开编辑时的接口类型与地址：改动后必须重新填写 Key（已保存的 Key 不会发往新地址） */
  orig_kind: '' as string,
  orig_base_url: '',
  models: [] as string[],
})

const normUrl = (u: string) => u.trim().replace(/\/+$/, '')
/** 编辑已有配置时改了地址或类型，却没有填写新 Key */
const needsNewKey = computed(
  () =>
    !!edit.id &&
    edit.has_key &&
    (!edit.api_key.trim() || edit.api_key.includes('***')) &&
    (edit.kind !== edit.orig_kind || normUrl(edit.base_url) !== normUrl(edit.orig_base_url)),
)
const KEY_REBIND_TIP = '修改了接口地址，请重新填写 API Key（已保存的 Key 不会发往新的地址）'

const baseUrlPlaceholder = '例如 https://api.deepseek.com/v1'

function applyPreset(id: string) {
  const p = presets.value.find((x) => x.id === id)
  if (!p) return
  edit.kind = (p.kind || 'openai_compatible') as LlmKind
  edit.base_url = p.base_url
  edit.model_vision = p.models.vision
  edit.model_chat = p.models.chat
  edit.model_fast = p.models.fast
  if (!edit.id) edit.name = p.name === '自定义' ? '' : p.name
  edit.models = []
}

function openCreate() {
  Object.assign(edit, {
    open: true,
    id: null,
    preset: 'custom',
    name: '',
    kind: 'openai_compatible' as LlmKind,
    base_url: '',
    api_key: '',
    model_vision: '',
    model_chat: '',
    model_fast: '',
    timeout_seconds: 90,
    anthropic_fallbacks: true,
    daily_token_budget: null,
    enabled: true,
    activate: true,
    masked: '',
    has_key: false,
    orig_kind: '',
    orig_base_url: '',
    models: [],
  })
  applyPreset('deepseek')
  edit.preset = 'deepseek'
}

function openEdit(p: LlmProvider) {
  Object.assign(edit, {
    open: true,
    id: p.id,
    preset: 'custom',
    name: p.name,
    kind: p.kind,
    base_url: p.base_url,
    api_key: '',
    model_vision: p.model_vision,
    model_chat: p.model_chat,
    model_fast: p.model_fast,
    timeout_seconds: p.timeout_seconds,
    anthropic_fallbacks: p.anthropic_fallbacks,
    daily_token_budget: p.daily_token_budget,
    enabled: p.enabled,
    activate: false,
    masked: p.api_key_masked,
    has_key: p.has_api_key,
    orig_kind: p.kind,
    orig_base_url: p.base_url,
    models: [],
  })
}

function payload() {
  return {
    name: edit.name.trim(),
    kind: edit.kind,
    base_url: edit.base_url.trim(),
    api_key: edit.api_key,
    model_vision: edit.model_vision.trim(),
    model_chat: edit.model_chat.trim(),
    model_fast: edit.model_fast.trim(),
    timeout_seconds: edit.timeout_seconds,
    anthropic_fallbacks: edit.anthropic_fallbacks,
    daily_token_budget: edit.daily_token_budget,
  }
}

function validate(): boolean {
  if (!edit.name.trim()) {
    ElMessage.warning('请填写名称')
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
  if (!edit.model_fast.trim() && !edit.model_chat.trim() && !edit.model_vision.trim()) {
    ElMessage.warning('至少填写一个模型名')
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
    if (edit.id) await updateLlmProvider(edit.id, { ...payload(), enabled: edit.enabled })
    else await createLlmProvider({ ...payload(), enabled: edit.enabled, activate: edit.activate })
    ElMessage.success('已保存')
    edit.open = false
    await load()
  } catch {
    /* 拦截器已提示 */
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
    edit.models = r.models
    if (!r.models.length) ElMessage.warning('接口没有返回模型，请手动填写')
    else ElMessage.success(`拉到 ${r.models.length} 个模型，可在下拉中选择`)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    edit.fetching = false
  }
}

// ---------------------------------------------------------------- 列表操作
async function activate(p: LlmProvider) {
  busy[`a-${p.id}`] = true
  try {
    await activateLlmProvider(p.id)
    ElMessage.success(`已切换到「${p.name}」`)
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[`a-${p.id}`] = false
  }
}

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
    if (r.ok) ElMessage.success(`连接成功（${r.model}）：${r.message}`)
    else ElMessage.error(`连接失败：${r.message}`)
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
    if (!enabled && p.is_active) p.is_active = false
    await load()
  } catch {
    /* 拦截器已提示 */
  }
}

async function remove(p: LlmProvider) {
  try {
    await ElMessageBox.confirm(`删除模型接入「${p.name}」？`, '删除接入', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteLlmProvider(p.id)
    ElMessage.success('已删除')
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
        <h2>模型接入</h2>
      </div>
      <div class="toolbar">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button v-if="auth.isAdmin" type="primary" :icon="Plus" @click="openCreate">添加接入</el-button>
      </div>
    </div>

    <el-card v-if="status" shadow="never" class="block current">
      <template #header>
        <div class="card-head">
          <span>当前生效</span>
          <el-tag :type="status.gateway.available ? 'success' : 'danger'" size="small">
            {{ status.gateway.available ? '可用' : '不可用' }}
          </el-tag>
        </div>
      </template>
      <el-descriptions :column="isMobile ? 1 : 2" size="small" border>
        <el-descriptions-item label="配置来源">
          <el-tag v-if="status.using_env" size="small" type="warning" effect="plain">环境变量（.env）</el-tag>
          <el-tag v-else size="small" type="success" effect="plain">{{ status.active_source }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="接口地址">
          <span class="mono small">{{ status.config.base_url || '默认地址' }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="今日用量">
          {{ status.gateway.usage_today.calls }} 次 /
          {{ tokenUsed.toLocaleString() }} tokens
          <span v-if="status.gateway.usage_today.budget" class="muted">
            （上限 {{ status.gateway.usage_today.budget.toLocaleString() }}）
          </span>
        </el-descriptions-item>
        <el-descriptions-item v-for="(m, tier) in status.gateway.models" :key="tier" :label="tierLabels[tier] || tier">
          <span class="mono small">{{ m || '未配置' }}</span>
        </el-descriptions-item>
      </el-descriptions>
      <el-alert
        v-if="status.using_env"
        class="mt"
        type="info"
        :closable="false"
        show-icon
        title="当前使用环境变量中的配置。添加一套接入并启用后，将优先使用管理台里的配置。"
      />
      <el-alert v-if="status.gateway.error" class="mt" type="error" :closable="false" show-icon :title="status.gateway.error" />
    </el-card>

    <el-alert
      v-if="!auth.isAdmin"
      class="mb"
      type="warning"
      :closable="false"
      show-icon
      title="只有管理员可以增删改模型接入配置，你可以在总览页查看当前状态。"
    />

    <template v-if="auth.isAdmin">
      <el-empty v-if="!loading && !providers.length" description="还没有配置接入，添加一套即可启用 AI 能力" />
      <div v-loading="loading" class="grid">
        <el-card v-for="p in providers" :key="p.id" shadow="never" class="prov" :class="{ active: p.is_active }">
          <div class="prov-head">
            <div class="prov-title-wrap">
              <span class="prov-name">{{ p.name }}</span>
              <el-tag v-if="p.is_active" size="small" type="success" class="ml">使用中</el-tag>
              <el-tag v-else-if="!p.enabled" size="small" type="info" class="ml">已停用</el-tag>
            </div>
            <el-switch :model-value="p.enabled" @change="(v: string | number | boolean) => toggle(p, !!v)" />
          </div>

          <div class="prov-body">
            <div class="row">
              <span class="muted small">地址</span>
              <span class="mono small ellipsis">{{ p.base_url || '默认地址' }}</span>
            </div>
            <div class="row">
              <span class="muted small">Key</span>
              <span class="mono small">{{ p.api_key_masked || '未填写' }}</span>
            </div>
            <div class="row">
              <span class="muted small">模型</span>
              <span class="small ellipsis">
                {{ [p.model_vision, p.model_chat, p.model_fast].filter(Boolean).join(' / ') || '未配置' }}
              </span>
            </div>
          </div>

          <div class="prov-test small">
            <template v-if="p.last_test_ok === true">
              <el-tag size="small" type="success" effect="plain">最近测试成功</el-tag>
              <span class="muted">{{ fmtTime(p.last_test_at) }}</span>
            </template>
            <template v-else-if="p.last_test_ok === false">
              <el-tag size="small" type="danger" effect="plain">最近测试失败</el-tag>
              <span class="muted ellipsis">{{ p.last_error }}</span>
            </template>
            <span v-else class="muted">尚未测试</span>
          </div>

          <div class="prov-ops">
            <el-button
              v-if="!p.is_active"
              size="small"
              type="primary"
              :disabled="!p.enabled"
              :loading="busy[`a-${p.id}`]"
              @click="activate(p)"
            >启用</el-button>
            <el-button size="small" :icon="Connection" :loading="busy[`t-${p.id}`]" @click="test(p)">测试</el-button>
            <el-button size="small" @click="openEdit(p)">编辑</el-button>
            <el-button size="small" type="danger" plain :icon="Delete" @click="remove(p)">删除</el-button>
          </div>
        </el-card>
      </div>
    </template>

    <el-dialog v-model="edit.open" :title="edit.id ? `编辑接入 · ${edit.name}` : '添加模型接入'" :width="isMobile ? '92%' : '600px'">
      <el-form label-width="110px" :label-position="isMobile ? 'top' : 'right'">
        <el-form-item v-if="!edit.id" label="快速预设">
          <el-select v-model="edit.preset" class="w260" @change="applyPreset">
            <el-option v-for="p in presets" :key="p.id" :value="p.id" :label="p.name" />
          </el-select>
        </el-form-item>

        <el-form-item label="名称" required>
          <el-input v-model="edit.name" maxlength="64" placeholder="例如：DeepSeek 主力" />
        </el-form-item>

        <el-form-item label="接口地址" required>
          <el-input v-model="edit.base_url" :placeholder="baseUrlPlaceholder" />
        </el-form-item>

        <el-form-item label="API Key" :required="!edit.id">
          <el-input
            v-model="edit.api_key"
            type="password"
            show-password
            :placeholder="edit.id && edit.has_key ? `已保存 ${edit.masked}，留空表示不修改` : 'sk-...'"
            autocomplete="off"
          />
          <div v-if="needsNewKey" class="form-tip warn">{{ KEY_REBIND_TIP }}</div>
        </el-form-item>

        <el-form-item label="模型名">
          <div class="models">
            <el-select
              v-for="t in [
                { key: 'model_vision', label: '多模态' },
                { key: 'model_chat', label: '对话' },
                { key: 'model_fast', label: '快速' },
              ]"
              :key="t.key"
              v-model="edit[t.key as 'model_vision' | 'model_chat' | 'model_fast']"
              filterable
              allow-create
              default-first-option
              clearable
              :placeholder="t.label"
              class="model-input"
            >
              <el-option v-for="m in edit.models" :key="m" :value="m" :label="m" />
            </el-select>
          </div>
          <div class="model-action-row">
            <el-button size="small" :loading="edit.fetching" @click="pullModels">从接口拉取模型列表</el-button>
          </div>
        </el-form-item>

        <el-form-item label="超时（秒）">
          <el-input-number v-model="edit.timeout_seconds" :min="5" :max="600" :step="5" controls-position="right" />
        </el-form-item>

        <el-form-item label="每日 Token 上限">
          <el-input-number v-model="edit.daily_token_budget" :min="0" :step="100000" controls-position="right" placeholder="留空沿用全局" />
        </el-form-item>

        <el-form-item label="启用">
          <el-switch v-model="edit.enabled" />
        </el-form-item>

        <el-form-item v-if="!edit.id" label="保存后启用">
          <el-switch v-model="edit.activate" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :loading="edit.testing" @click="probe">测试连接</el-button>
        <el-button @click="edit.open = false">取消</el-button>
        <el-button type="primary" :loading="edit.saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.block {
  margin-bottom: 12px;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
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
.prov.active {
  border-color: var(--el-color-success);
}
.prov-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.prov-name {
  font-weight: 600;
  font-size: 15px;
  margin-bottom: 4px;
}
.prov-body {
  background: #f7f8fa;
  border-radius: 6px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.row {
  display: flex;
  gap: 8px;
  min-width: 0;
}
.row > span:first-child {
  flex: 0 0 40px;
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
}
.prov-ops .el-button + .el-button {
  margin-left: 0;
}
.models {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}
.model-input {
  width: 150px;
}
.w260 {
  width: 260px;
  max-width: 100%;
}
.ml {
  margin-left: 8px;
}
.mb {
  margin-bottom: 12px;
}
.form-tip.warn {
  color: var(--el-color-warning);
}
</style>
