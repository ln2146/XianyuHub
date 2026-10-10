<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, Delete, Download, InfoFilled, Plus, Refresh } from '@element-plus/icons-vue'
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
const activePresetNote = computed(() => presets.value.find((x) => x.id === edit.preset)?.note || '')

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
      <div v-if="!loading && !providers.length" class="empty-state-card">
        <el-empty description="尚未配置大模型接入，配置后可启用智能客服问答、闲鱼好货质检与转手文案生成">
          <el-button type="primary" :icon="Plus" @click="openCreate">立即添加大模型接入</el-button>
        </el-empty>
      </div>
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

    <el-dialog
      v-model="edit.open"
      :title="edit.id ? `编辑接入 · ${edit.name}` : '添加模型接入'"
      :width="isMobile ? '94%' : '660px'"
      :close-on-click-modal="false"
      class="model-dialog"
    >
      <el-form label-width="118px" :label-position="isMobile ? 'top' : 'right'" class="model-form">
        <el-form-item v-if="!edit.id" label="快速预设">
          <div class="preset-field-wrap">
            <el-select v-model="edit.preset" class="full-width" placeholder="选择供应商预设，快速填入配置" @change="applyPreset">
              <el-option v-for="p in presets" :key="p.id" :value="p.id" :label="p.name">
                <div class="preset-option-row">
                  <span class="preset-option-name">{{ p.name }}</span>
                  <span v-if="p.note" class="preset-option-note">{{ p.note }}</span>
                </div>
              </el-option>
            </el-select>
            <div v-if="activePresetNote" class="preset-hint">
              <el-icon class="preset-hint-icon"><InfoFilled /></el-icon>
              <span>{{ activePresetNote }}</span>
            </div>
          </div>
        </el-form-item>

        <el-form-item label="名称" required>
          <el-input v-model="edit.name" maxlength="64" placeholder="例如：阿里、DeepSeek 主力" />
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
            autocomplete="new-password"
          />
          <div v-if="needsNewKey" class="form-tip warn">{{ KEY_REBIND_TIP }}</div>
        </el-form-item>

        <el-form-item label="模型配置">
          <div class="model-slots-container">
            <div class="model-slots-grid">
              <div class="model-slot-card">
                <div class="slot-header">
                  <span class="slot-title">对话主力</span>
                  <span class="slot-role">客服问答</span>
                </div>
                <el-select
                  v-model="edit.model_chat"
                  filterable
                  allow-create
                  default-first-option
                  clearable
                  placeholder="如 qwen-plus"
                  class="full-width"
                >
                  <el-option v-for="m in edit.models" :key="m" :value="m" :label="m" />
                </el-select>
              </div>

              <div class="model-slot-card">
                <div class="slot-header">
                  <span class="slot-title">多模态</span>
                  <span class="slot-role">看图发品</span>
                </div>
                <el-select
                  v-model="edit.model_vision"
                  filterable
                  allow-create
                  default-first-option
                  clearable
                  placeholder="如 qwen-vl-max"
                  class="full-width"
                >
                  <el-option v-for="m in edit.models" :key="m" :value="m" :label="m" />
                </el-select>
              </div>

              <div class="model-slot-card">
                <div class="slot-header">
                  <span class="slot-title">快速轻量</span>
                  <span class="slot-role">意图分类</span>
                </div>
                <el-select
                  v-model="edit.model_fast"
                  filterable
                  allow-create
                  default-first-option
                  clearable
                  placeholder="如 qwen-turbo"
                  class="full-width"
                >
                  <el-option v-for="m in edit.models" :key="m" :value="m" :label="m" />
                </el-select>
              </div>
            </div>

            <div class="model-fetch-row">
              <el-button size="small" :icon="Download" :loading="edit.fetching" @click="pullModels">
                从接口拉取模型列表
              </el-button>
              <span class="fetch-tip">
                {{ edit.models.length ? `已获取 ${edit.models.length} 个可用模型` : '填写接口与 Key 后可在线查询可用模型' }}
              </span>
            </div>
          </div>
        </el-form-item>

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
            <el-form-item label="每日 Token 预算">
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

        <el-form-item label="运行设置">
          <div class="setting-switches-group">
            <div class="setting-switch-item">
              <el-switch v-model="edit.enabled" />
              <div class="switch-text">
                <span class="switch-title">启用此服务</span>
                <span class="switch-desc">关闭后系统将不再使用该接入分发请求</span>
              </div>
            </div>
            <div v-if="!edit.id" class="setting-switch-item">
              <el-switch v-model="edit.activate" />
              <div class="switch-text">
                <span class="switch-title">设为当前主力</span>
                <span class="switch-desc">保存后立即切换为当前默认大模型生效</span>
              </div>
            </div>
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="dialog-footer-content">
          <el-button :icon="Connection" :loading="edit.testing" @click="probe">测试连接</el-button>
          <div class="footer-right-buttons">
            <el-button @click="edit.open = false">取消</el-button>
            <el-button type="primary" :loading="edit.saving" @click="save">保存接入</el-button>
          </div>
        </div>
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
.empty-state-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-lg);
  padding: var(--xh-space-8) var(--xh-space-4);
  display: flex;
  justify-content: center;
}
.prov-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.prov-name {
  font-weight: 600;
  font-size: var(--xh-fs-md);
  margin-bottom: 4px;
  color: var(--xh-text);
}
.prov-body {
  background: var(--xh-fill);
  border-radius: var(--xh-radius-sm);
  border: 1px solid var(--xh-border);
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
.ml {
  margin-left: 8px;
}
.mb {
  margin-bottom: 12px;
}
.form-tip.warn {
  color: var(--el-color-warning);
}

/* ---------- 弹窗表单样式优化 ---------- */
.full-width {
  width: 100% !important;
}
:deep(.model-form .el-form-item__label) {
  font-weight: 500;
  color: var(--xh-text);
  white-space: nowrap;
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
  font-size: 14px;
  flex-shrink: 0;
}

.model-slots-container {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.model-slots-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  width: 100%;
}
@media (max-width: 600px) {
  .model-slots-grid {
    grid-template-columns: 1fr;
  }
}
.model-slot-card {
  background: #f8fafc;
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-sm);
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.slot-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: 12px;
}
.slot-title {
  font-weight: 600;
  color: var(--xh-text);
}
.slot-role {
  font-size: 11px;
  color: var(--xh-text-muted);
}
.model-fetch-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 2px;
}
.fetch-tip {
  font-size: 12px;
  color: var(--xh-text-muted);
}

.setting-switches-group {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  background: #f8fafc;
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-sm);
  padding: 10px 14px;
  width: 100%;
}
.setting-switch-item {
  display: flex;
  align-items: center;
  gap: 10px;
}
.switch-text {
  display: flex;
  flex-direction: column;
}
.switch-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--xh-text);
  line-height: 1.2;
}
.switch-desc {
  font-size: 11px;
  color: var(--xh-text-muted);
  line-height: 1.3;
  margin-top: 2px;
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
</style>
