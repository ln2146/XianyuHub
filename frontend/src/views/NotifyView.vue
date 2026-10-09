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
const meta = ref<NotifyMeta>({ types: {}, events: [] })
const channels = ref<Channel[]>([])
const loading = ref(false)
const busy = reactive<Record<string, boolean>>({})

/** 配置项的中文名称与提示 */
const fieldMeta: Record<string, { label: string; placeholder?: string; secret?: boolean; type?: 'number' | 'bool' | 'json' }> = {
  webhook_url: { label: 'Webhook 地址', placeholder: '机器人 Webhook URL', secret: true },
  bot_token: { label: 'Bot Token', placeholder: '123456:ABC-DEF…', secret: true },
  chat_id: { label: 'Chat ID', placeholder: '用户或群组 ID' },
  api_base: { label: 'API 地址', placeholder: 'https://api.telegram.org（可用反代地址）' },
  server_url: { label: '服务器地址', placeholder: 'https://api.day.app 或 https://ntfy.sh' },
  device_key: { label: 'Device Key', secret: true },
  topic: { label: '主题 Topic', placeholder: '订阅的 topic 名称' },
  token: { label: '访问令牌', placeholder: '可选', secret: true },
  url: { label: '回调地址', placeholder: 'https://your-server/hook（POST JSON）', secret: true },
  headers: { label: '请求头', placeholder: '{"Authorization": "Bearer xxx"}', type: 'json' },
  host: { label: 'SMTP 服务器', placeholder: 'smtp.qq.com' },
  port: { label: '端口', placeholder: '465', type: 'number' },
  ssl: { label: '使用 SSL', type: 'bool' },
  username: { label: '发件邮箱', placeholder: 'you@example.com' },
  password: { label: '密码 / 授权码', secret: true },
  to: { label: '收件邮箱', placeholder: 'to@example.com' },
}

/** 后端 meta 只返回必填项，这里补充可选项 */
const optionalFields: Record<string, string[]> = {
  telegram: ['api_base'],
  ntfy: ['server_url', 'token'],
  webhook: ['headers'],
  email: ['port', 'ssl'],
}

const typeHelp: Record<string, string> = {
  wecom: '企业微信群 → 添加群机器人 → 复制 Webhook 地址',
  feishu: '飞书群 → 设置 → 群机器人 → 自定义机器人',
  dingtalk: '钉钉群 → 智能群助手 → 自定义机器人（安全设置建议用关键词「鱼塘」）',
  telegram: '通过 @BotFather 创建机器人获取 Token，向机器人发消息后获取 Chat ID',
  bark: 'iOS 安装 Bark App，复制推送地址中的服务器与 Key',
  ntfy: '手机安装 ntfy App 并订阅同名 topic',
  webhook: '以 POST JSON 推送 {event, title, content, url…} 到你的服务',
  email: 'QQ / 163 邮箱需使用 SMTP 授权码而非登录密码',
}

async function load() {
  loading.value = true
  try {
    const [m, list] = await Promise.all([getNotifyMeta(), listChannels()])
    meta.value = m
    channels.value = list
  } finally {
    loading.value = false
  }
}
onMounted(load)

// ---------------------------------------------------------------- 编辑
const edit = reactive({
  open: false,
  saving: false,
  id: null as number | null,
  name: '',
  type: '',
  config: {} as Record<string, string>,
  bools: {} as Record<string, boolean>,
  events: [] as string[],
  enabled: true,
})

const fields = computed(() => {
  const req = meta.value.types[edit.type] || []
  const opt = (optionalFields[edit.type] || []).filter((f) => !req.includes(f))
  return [...req.map((k) => ({ key: k, required: true })), ...opt.map((k) => ({ key: k, required: false }))]
})

function openCreate() {
  const first = Object.keys(meta.value.types)[0] || 'wecom'
  Object.assign(edit, { open: true, id: null, name: '', type: first, config: {}, bools: { ssl: true }, events: [], enabled: true })
}

function openEdit(c: Channel) {
  const cfg: Record<string, string> = {}
  const bools: Record<string, boolean> = {}
  for (const [k, v] of Object.entries(c.config)) {
    if (typeof v === 'boolean') bools[k] = v
    else if (typeof v === 'object' && v !== null) cfg[k] = JSON.stringify(v)
    else if (v !== null && v !== undefined) cfg[k] = String(v)
  }
  Object.assign(edit, { open: true, id: c.id, name: c.name, type: c.type, config: cfg, bools, events: [...c.events], enabled: c.enabled })
}

function buildConfig(): Record<string, unknown> | null {
  const out: Record<string, unknown> = {}
  for (const f of fields.value) {
    const fm = fieldMeta[f.key]
    if (fm?.type === 'bool') {
      out[f.key] = edit.bools[f.key] ?? true
      continue
    }
    const v = (edit.config[f.key] ?? '').trim()
    if (!v) {
      if (f.required) {
        ElMessage.warning(`请填写${fm?.label || f.key}`)
        return null
      }
      continue
    }
    if (fm?.type === 'json') {
      try {
        out[f.key] = JSON.parse(v)
      } catch {
        ElMessage.warning(`${fm.label} 不是有效的 JSON`)
        return null
      }
    } else if (fm?.type === 'number') {
      out[f.key] = Number(v)
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
        <div class="sub">好货推荐、降价、风控、新订单、发货失败等事件推送到你常用的 App</div>
      </div>
      <div class="toolbar">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">添加渠道</el-button>
      </div>
    </div>

    <el-empty v-if="!loading && !channels.length" description="还没有通知渠道，添加一个以便及时收到好货与异常提醒" />
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
            <span class="muted">{{ fieldMeta[k]?.label || k }}：</span>
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
        <el-form-item v-for="f in fields" :key="f.key" :label="fieldMeta[f.key]?.label || f.key" :required="f.required">
          <el-switch v-if="fieldMeta[f.key]?.type === 'bool'" :model-value="edit.bools[f.key] ?? true" @update:model-value="(v: string | number | boolean) => (edit.bools[f.key] = !!v)" />
          <el-input
            v-else
            v-model="edit.config[f.key]"
            :type="fieldMeta[f.key]?.type === 'json' ? 'textarea' : 'text'"
            :rows="3"
            :placeholder="fieldMeta[f.key]?.placeholder || (f.required ? '必填' : '可选')"
            :show-password="!!fieldMeta[f.key]?.secret && !edit.id"
          />
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
.ch-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.ch-name {
  font-weight: 600;
  font-size: 15px;
  margin-bottom: 4px;
}
.ch-events {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}
.ch-cfg {
  background: #f7f8fa;
  border-radius: 6px;
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
