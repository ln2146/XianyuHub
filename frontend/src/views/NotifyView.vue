<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import {
  createChannel,
  deleteChannel,
  getNotifyMeta,
  listChannels,
  testChannel,
  updateChannel,
  type Channel,
  type NotifyMeta,
} from '@/api/notify'
import { useMobile } from '@/composables/useMobile'
import { notifyEventMap, notifyTypeMap } from '@/utils/format'

const isMobile = useMobile()
const meta = ref<NotifyMeta>({ types: {}, optional: {}, events: [] })
const channels = ref<Channel[]>([])
const loading = ref(false)
const busy = reactive<Record<string, boolean>>({})

/** 配置项的中文名称与提示（未列出的字段直接显示原始字段名） */
const fieldMeta: Record<string, { label: string; placeholder?: string; secret?: boolean }> = {
  webhook_url: { label: 'Webhook 地址', placeholder: '机器人 Webhook URL', secret: true },
  bot_token: { label: 'Bot Token', placeholder: '123456:ABC-DEF…', secret: true },
  chat_id: { label: 'Chat ID', placeholder: '用户或群组 ID' },
  api_base: { label: 'API 地址', placeholder: 'https://api.telegram.org（可用反代地址）' },
  server_url: { label: '服务器地址', placeholder: 'https://api.day.app 或 https://ntfy.sh' },
  device_key: { label: 'Device Key', secret: true },
  topic: { label: '主题 Topic', placeholder: '订阅的 topic 名称' },
  token: { label: '访问令牌 / Token', secret: true },
  sendkey: { label: 'SendKey', placeholder: 'SCT… 或 sctp…', secret: true },
  url: { label: '回调地址', placeholder: 'https://your-server/hook（POST JSON）', secret: true },
  headers: { label: '请求头', placeholder: '{"Authorization": "Bearer xxx"}' },
  host: { label: 'SMTP 服务器', placeholder: 'smtp.qq.com' },
  port: { label: '端口' },
  ssl: { label: '使用 SSL' },
  starttls: { label: 'STARTTLS' },
  secret: { label: '签名密钥', placeholder: '机器人安全设置里的加签 / 签名校验密钥', secret: true },
  username: { label: '发件邮箱', placeholder: 'you@example.com' },
  password: { label: '密码 / 授权码', secret: true },
  to: { label: '收件邮箱', placeholder: 'to@example.com' },
}
const labelOf = (k: string) => fieldMeta[k]?.label || k

const typeHelp: Record<string, string> = {
  serverchan: '推送到个人微信：在 sct.ftqq.com 用微信扫码登录，复制 SendKey（Turbo 版 SCT… 和 Server酱³ sctp… 都可以）',
  pushplus: '推送到个人微信：在 pushplus.plus 微信扫码登录，复制「一对一推送」的 Token',
  wecom: '企业微信群 → 添加群机器人 → 复制 Webhook 地址',
  feishu: '飞书群 → 设置 → 群机器人 → 自定义机器人；开启了「签名校验」就把密钥填到下方',
  dingtalk: '钉钉群 → 智能群助手 → 自定义机器人；安全设置选「加签」并把 SEC 开头的密钥填到下方（选「自定义关键词」则需包含通知标题里的字）',
  telegram: '通过 @BotFather 创建机器人获取 Token，向机器人发消息后获取 Chat ID',
  bark: 'iOS 安装 Bark App，复制推送地址中的服务器与 Key',
  ntfy: '手机安装 ntfy App 并订阅同名 topic',
  webhook: '以 POST JSON 推送 {event, title, content, url…} 到你的服务',
  email: 'QQ / 163 邮箱需使用 SMTP 授权码而非登录密码；465 端口开启 SSL，587 端口关闭 SSL 并保持 STARTTLS 开启',
}

async function load() {
  loading.value = true
  try {
    const [m, list] = await Promise.all([getNotifyMeta(), listChannels()])
    meta.value = { types: m.types || {}, optional: m.optional || {}, events: m.events || [] }
    channels.value = list
  } finally {
    loading.value = false
  }
}
onMounted(load)

// ---------------------------------------------------------------- 编辑
/** 字段控件类型：必填项均为文本；可选项按后端默认值的类型推断 */
type FieldKind = 'string' | 'number' | 'boolean' | 'json'
interface FieldDef {
  key: string
  required: boolean
  kind: FieldKind
  default: unknown
}

function kindOf(v: unknown): FieldKind {
  if (typeof v === 'number') return 'number'
  if (typeof v === 'boolean') return 'boolean'
  if (typeof v === 'object' && v !== null) return 'json'
  return 'string'
}

const edit = reactive({
  open: false,
  saving: false,
  id: null as number | null,
  name: '',
  type: '',
  /** 文本 / JSON 字段的输入值 */
  config: {} as Record<string, string>,
  nums: {} as Record<string, number | null | undefined>,
  bools: {} as Record<string, boolean>,
  events: [] as string[],
  enabled: true,
})

const fields = computed<FieldDef[]>(() => {
  const req = meta.value.types[edit.type] || []
  const opt = Object.entries(meta.value.optional[edit.type] || {}).filter(([k]) => !req.includes(k))
  return [
    ...req.map((k) => ({ key: k, required: true, kind: 'string' as FieldKind, default: '' })),
    ...opt.map(([k, d]) => ({ key: k, required: false, kind: kindOf(d), default: d })),
  ]
})

function placeholderOf(f: FieldDef): string {
  const custom = fieldMeta[f.key]?.placeholder
  if (f.required) return custom || '必填'
  if (f.kind === 'json') return custom || `JSON，例如 ${JSON.stringify(f.default)}`
  if (typeof f.default === 'string' && f.default) return `可选，默认 ${f.default}`
  return custom ? `${custom}（可选）` : '可选'
}

const numValue = (f: FieldDef) => edit.nums[f.key] ?? (typeof f.default === 'number' ? f.default : undefined)
const boolValue = (f: FieldDef) => edit.bools[f.key] ?? f.default === true

function openCreate() {
  const first = Object.keys(meta.value.types)[0] || 'wecom'
  Object.assign(edit, { open: true, id: null, name: '', type: first, config: {}, nums: {}, bools: {}, events: [], enabled: true })
}

function openEdit(c: Channel) {
  const cfg: Record<string, string> = {}
  const nums: Record<string, number> = {}
  const bools: Record<string, boolean> = {}
  for (const [k, v] of Object.entries(c.config)) {
    if (typeof v === 'boolean') bools[k] = v
    else if (typeof v === 'number') {
      nums[k] = v
      cfg[k] = String(v)
    } else if (typeof v === 'object' && v !== null) cfg[k] = JSON.stringify(v, null, 2)
    else if (v !== null && v !== undefined) cfg[k] = String(v)
  }
  Object.assign(edit, { open: true, id: c.id, name: c.name, type: c.type, config: cfg, nums, bools, events: [...c.events], enabled: c.enabled })
}

function buildConfig(): Record<string, unknown> | null {
  const out: Record<string, unknown> = {}
  for (const f of fields.value) {
    if (f.kind === 'boolean') {
      out[f.key] = boolValue(f)
      continue
    }
    if (f.kind === 'number') {
      const n = numValue(f)
      if (n !== undefined && n !== null && Number.isFinite(n)) out[f.key] = n
      continue
    }
    const v = (edit.config[f.key] ?? '').trim()
    if (!v) {
      if (f.required) {
        ElMessage.warning(`请填写${labelOf(f.key)}`)
        return null
      }
      continue
    }
    if (f.kind === 'json') {
      let parsed: unknown
      try {
        parsed = JSON.parse(v)
      } catch {
        ElMessage.warning(`${labelOf(f.key)} 不是有效的 JSON`)
        return null
      }
      const wantArray = Array.isArray(f.default)
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed) !== wantArray) {
        ElMessage.warning(`${labelOf(f.key)} 必须是 JSON ${wantArray ? '数组' : '对象'}`)
        return null
      }
      out[f.key] = parsed
    } else {
      out[f.key] = v
    }
  }
  return out
}

async function save() {
  if (!edit.name.trim()) return ElMessage.warning('请填写名称')
  const config = buildConfig()
  if (!config) return
  edit.saving = true
  try {
    if (edit.id) await updateChannel(edit.id, { name: edit.name.trim(), config, events: edit.events, enabled: edit.enabled })
    else await createChannel({ name: edit.name.trim(), type: edit.type, config, events: edit.events, enabled: edit.enabled })
    ElMessage.success('已保存')
    edit.open = false
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    edit.saving = false
  }
}

async function test(c: Channel) {
  busy[`t-${c.id}`] = true
  try {
    const r = await testChannel(c.id)
    if (r.ok) ElMessage.success('测试消息已发送，请检查是否收到')
    else ElMessage.error(`发送失败：${r.error}`)
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[`t-${c.id}`] = false
  }
}

async function toggle(c: Channel, enabled: boolean) {
  try {
    await updateChannel(c.id, { enabled })
    c.enabled = enabled
  } catch {
    /* 拦截器已提示 */
  }
}

async function remove(c: Channel) {
  await ElMessageBox.confirm(`删除通知渠道「${c.name}」？`, '删除渠道', { type: 'warning' })
  await deleteChannel(c.id)
  ElMessage.success('已删除')
  await load()
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>通知设置</h2>
      </div>
      <div class="toolbar">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">添加渠道</el-button>
      </div>
    </div>

    <div v-if="!loading && !channels.length" class="empty-state-card">
      <el-empty description="尚未配置任何通知渠道，下单、待发货及账号风控等消息将无法即时推送到手机">
        <el-button type="primary" :icon="Plus" @click="openCreate">立即添加第一个通知渠道</el-button>
      </el-empty>
    </div>
    <div v-loading="loading" class="grid">
      <el-card v-for="c in channels" :key="c.id" shadow="never" class="ch">
        <div class="ch-head">
          <div>
            <div class="ch-name">{{ c.name }}</div>
            <el-tag size="small" effect="plain">{{ notifyTypeMap[c.type] || c.type }}</el-tag>
          </div>
          <el-switch :model-value="c.enabled" @change="(v: string | number | boolean) => toggle(c, !!v)" />
        </div>
        <div class="ch-events">
          <span class="muted small">订阅：</span>
          <template v-if="c.events.length">
            <el-tag v-for="e in c.events" :key="e" size="small" type="info">{{ notifyEventMap[e] || e }}</el-tag>
          </template>
          <el-tag v-else size="small" type="success">全部事件</el-tag>
        </div>
        <div class="ch-cfg">
          <div v-for="(v, k) in c.config" :key="k" class="small ellipsis">
            <span class="muted">{{ labelOf(String(k)) }}：</span>
            <span class="mono">{{ typeof v === 'object' ? JSON.stringify(v) : v }}</span>
          </div>
        </div>
        <el-alert v-if="c.last_error" :title="`最近一次发送失败：${c.last_error}`" type="error" :closable="false" class="ch-err" />
        <div class="ch-ops">
          <el-button size="small" type="primary" plain :loading="busy[`t-${c.id}`]" @click="test(c)">测试</el-button>
          <el-button size="small" @click="openEdit(c)">编辑</el-button>
          <el-button size="small" type="danger" plain @click="remove(c)">删除</el-button>
        </div>
      </el-card>
    </div>

    <el-dialog v-model="edit.open" :title="edit.id ? '编辑通知渠道' : '添加通知渠道'" width="600px">
      <el-form label-width="110px" :label-position="isMobile ? 'top' : 'right'">
        <el-form-item label="名称" required>
          <el-input v-model="edit.name" maxlength="64" placeholder="例如：我的企业微信群" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="edit.type" :disabled="!!edit.id" class="w240">
            <el-option v-for="(_, t) in meta.types" :key="t" :value="t" :label="notifyTypeMap[t] || t" />
          </el-select>
          <div v-if="typeHelp[edit.type]" class="form-tip">{{ typeHelp[edit.type] }}</div>
        </el-form-item>
        <el-form-item v-for="f in fields" :key="`${edit.type}-${f.key}`" :label="labelOf(f.key)" :required="f.required">
          <el-switch
            v-if="f.kind === 'boolean'"
            :model-value="boolValue(f)"
            @update:model-value="(v: string | number | boolean) => (edit.bools[f.key] = !!v)"
          />
          <el-input-number
            v-else-if="f.kind === 'number'"
            :model-value="numValue(f)"
            :min="0"
            :step="1"
            :step-strictly="Number.isInteger(f.default)"
            controls-position="right"
            @update:model-value="(v: number | null | undefined) => (edit.nums[f.key] = v)"
          />
          <el-input
            v-else
            v-model="edit.config[f.key]"
            :type="f.kind === 'json' ? 'textarea' : 'text'"
            :rows="f.kind === 'json' ? 4 : undefined"
            :class="{ mono: f.kind === 'json' }"
            :placeholder="placeholderOf(f)"
            :show-password="!!fieldMeta[f.key]?.secret && !edit.id"
          />
          <div v-if="f.kind === 'json'" class="form-tip">填写 JSON {{ Array.isArray(f.default) ? '数组' : '对象' }}，留空使用默认值；保存时会校验格式。</div>
          <div v-else-if="!f.required && f.kind !== 'string'" class="form-tip">默认：{{ typeof f.default === 'boolean' ? (f.default ? '开启' : '关闭') : f.default }}</div>
          <div v-if="edit.id && fieldMeta[f.key]?.secret" class="form-tip">显示为 *** 的值表示保持不变。</div>
        </el-form-item>
        <el-form-item label="订阅事件">
          <el-checkbox-group v-model="edit.events">
            <el-checkbox v-for="e in meta.events" :key="e" :value="e">{{ notifyEventMap[e] || e }}</el-checkbox>
          </el-checkbox-group>
          <div class="form-tip">不勾选任何事件表示订阅全部。</div>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="edit.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="edit.open = false">取消</el-button>
        <el-button type="primary" :loading="edit.saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}
.ch :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
}
.empty-state-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-lg);
  padding: var(--xh-space-8) var(--xh-space-4);
  display: flex;
  justify-content: center;
}
.ch-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.ch-name {
  font-weight: 600;
  font-size: var(--xh-fs-md);
  margin-bottom: 4px;
  color: var(--xh-text);
}
.ch-events {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}
.ch-cfg {
  background: var(--xh-fill);
  border-radius: var(--xh-radius-sm);
  border: 1px solid var(--xh-border);
  padding: 8px;
}
.ch-err {
  padding: 6px 8px;
}
.ch-ops {
  display: flex;
  gap: 6px;
  margin-top: auto;
}
.ch-ops .el-button + .el-button {
  margin-left: 0;
}
.w240 {
  width: 240px;
  max-width: 100%;
}
</style>
