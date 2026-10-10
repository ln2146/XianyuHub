<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Check,
  CircleCheck,
  Connection,
  Delete,
  Edit,
  Hide,
  Refresh,
  Search,
  View,
  WarningFilled,
} from '@element-plus/icons-vue'
import {
  createChannel,
  deleteChannel,
  getNotifyMeta,
  listChannels,
  testChannel,
  testUnsavedChannel,
  updateChannel,
  type Channel,
  type NotifyMeta,
} from '@/api/notify'
import ConnectorIcon from '@/components/ConnectorIcon.vue'
import { useMobile } from '@/composables/useMobile'
import { notifyEventMap, notifyTypeMap } from '@/utils/format'

const isMobile = useMobile()
const meta = ref<NotifyMeta>({ types: {}, optional: {}, events: [] })
const channels = ref<Channel[]>([])
const loading = ref(false)
const busy = reactive<Record<string, boolean>>({})

// 顶部 Tab 切换：'market' (应用连接器市场) | 'connected' (已连接渠道管理)
const activeTab = ref<'market' | 'connected'>('market')
const searchQuery = ref('')
const selectedCategory = ref('all')

/** 密码/密钥字段显隐状态 */
const showSecrets = reactive<Record<string, boolean>>({})

/** 应用连接器定义 */
interface ConnectorApp {
  type: string
  name: string
  subTag?: string
  category: 'collab' | 'mobile' | 'email' | 'dev'
  categoryLabel: string
  desc: string
  guide: string
  badge?: string
}

const connectorApps: ConnectorApp[] = [
  {
    type: 'wecom',
    name: '企业微信',
    category: 'collab',
    categoryLabel: '办公协作',
    desc: '通过企业微信群机器人 Webhook，将闲鱼订单付款、发货异常、客服转人工与账号风控预警实时推送到指定工作群，支持 Markdown 卡片。',
    guide: '在企业微信群中点击「设置」→「群机器人」→「添加机器人」，复制生成的 Webhook 地址粘贴到下方即可。',
  },
  {
    type: 'feishu',
    name: '飞书',
    category: 'collab',
    categoryLabel: '办公协作',
    desc: '通过飞书群自定义机器人，实时接收闲鱼订单动态、新买家咨询与商品降价预警，支持交互式富文本卡片排版与签名校验。',
    guide: '在飞书群「设置」→「群机器人」添加「自定义机器人」，复制 Webhook 地址；若开启了「签名校验」，请将密钥一并填入下方。',
  },
  {
    type: 'dingtalk',
    name: '钉钉',
    category: 'collab',
    categoryLabel: '办公协作',
    desc: '通过钉钉群智能助手自定义机器人，即时同步店铺新订单、库存紧缺告警与买家咨询，支持加签安全验证。',
    guide: '在钉钉群「智能群助手」添加「自定义机器人」，安全设置选「加签」，并把 SEC 开头的密钥填到下方。',
  },
  {
    type: 'email',
    name: 'QQ邮箱 / 常用邮箱',
    category: 'email',
    categoryLabel: '邮箱通知',
    desc: '通过 SMTP 协议将每日交易汇总、发货失败异常与风控预警直发收件箱，支持 QQ邮箱、163 邮箱与企业域名邮箱。',
    guide: 'QQ 或 163 邮箱需登录网页端开启 POP3/SMTP 服务并生成「专属授权码」；QQ 邮箱 465 端口开启 SSL，587 端口开启 STARTTLS。',
  },
  {
    type: 'serverchan',
    name: '微信服务号',
    subTag: 'Server酱',
    category: 'mobile',
    categoryLabel: '微信与手机',
    desc: '通过微信服务号模板消息推送，将闲鱼订单付款、发货异常、客服求助与账号风控实时推送到个人微信，免装单独 App，微信即刻弹窗提醒。',
    guide: '在 sct.ftqq.com 微信扫码登录，复制 SendKey（Turbo 版 SCT… 或 Server酱³ sctp… 均可）粘贴到下方即可。',
  },
  {
    type: 'pushplus',
    name: '微信公众号',
    subTag: 'PushPlus',
    category: 'mobile',
    categoryLabel: '微信与手机',
    desc: '微信扫码关注公众号即可一对一绑定，闲鱼新订单、买家未读与转人工提醒直接微信公众号弹窗，轻量省电。',
    guide: '在 pushplus.plus 微信扫码登录，复制个人中心「一对一推送」的 Token 粘贴到下方即可。',
  },
  {
    type: 'bark',
    name: 'Bark (iOS极速推送)',
    category: 'mobile',
    categoryLabel: '微信与手机',
    desc: '专为 iPhone / iPad / Apple Watch 打造的原生秒级通知，闲鱼成交与紧急预警一键触达，支持自定义铃声与角标。',
    guide: 'iOS App Store 安装 Bark App，复制 App 内提供的服务器地址与 Device Key 填入下方即可。',
  },
  {
    type: 'telegram',
    name: 'Telegram',
    category: 'dev',
    categoryLabel: '开发与系统',
    desc: '通过 Telegram 机器人即时推送订单与操作日志，全球极速触达，支持多群组、频道与自定义反代端点。',
    guide: '通过 @BotFather 创建机器人获取 Bot Token，向机器人发送任意消息后获取 Chat ID；国内服务器可配置反代地址。',
  },
  {
    type: 'ntfy',
    name: 'ntfy',
    category: 'mobile',
    categoryLabel: '微信与手机',
    desc: '基于开源 ntfy 的跨平台即时推送协议，手机安装 App 订阅 Topic 即可接收即时通知，免注册、完全私密。',
    guide: '手机安装 ntfy App 并新建订阅一个专属 Topic，在下方填入相同的 Topic 名称即可接收通知。',
  },
  {
    type: 'webhook',
    name: '自定义 Webhook',
    category: 'dev',
    categoryLabel: '开发与系统',
    desc: '以标准 POST JSON 方式将所有交易与告警事件推送至你的私有自动化系统、Python 脚本或第三方 ERP。',
    guide: '填写你的服务回调 URL 与可选自定义 Header，每当事件触发时将以 POST JSON 发送通知载荷。',
  },
]

/** 分类过滤选项 */
const categories = [
  { key: 'all', label: '全部连接器' },
  { key: 'collab', label: '办公协作' },
  { key: 'mobile', label: '微信与手机' },
  { key: 'email', label: '邮箱通知' },
  { key: 'dev', label: '开发与系统' },
]

/** 筛选后的连接器列表 */
const filteredConnectors = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  const cat = selectedCategory.value
  return connectorApps.filter((app) => {
    const matchCat = cat === 'all' || app.category === cat
    const matchQuery =
      !q ||
      app.name.toLowerCase().includes(q) ||
      (app.subTag && app.subTag.toLowerCase().includes(q)) ||
      app.desc.toLowerCase().includes(q) ||
      app.categoryLabel.toLowerCase().includes(q) ||
      app.type.toLowerCase().includes(q)
    return matchCat && matchQuery
  })
})

/** 获取某类型已配置渠道数量 */
function getConnectedCount(type: string): number {
  return channels.value.filter((c) => c.type === type).length
}

/** 事件分组展示定义 */
interface EventGroup {
  name: string
  icon: string
  events: string[]
}

const eventGroups: EventGroup[] = [
  {
    name: '交易与订单',
    icon: '📦',
    events: ['order_paid', 'delivery_failed', 'stock_low'],
  },
  {
    name: '买家与客服',
    icon: '💬',
    events: ['new_message', 'human_handoff'],
  },
  {
    name: '选品与雷达',
    icon: '🎯',
    events: ['item_recommended', 'price_drop', 'task_failed'],
  },
  {
    name: '账号与安全',
    icon: '🛡️',
    events: ['account_risk', 'account_login_required'],
  },
]

/** 配置项的中文名称与提示 */
const fieldMeta: Record<string, { label: string; placeholder?: string; secret?: boolean }> = {
  webhook_url: { label: 'Webhook 地址', placeholder: 'https://qyapi.weixin.qq.com/... 或飞书/钉钉机器人的 Webhook URL', secret: true },
  bot_token: { label: 'Bot Token', placeholder: '123456789:ABCdefGhIJKlmNoPQ...', secret: true },
  chat_id: { label: 'Chat ID', placeholder: '用户或群组 ID，例如 -100123456789' },
  api_base: { label: 'API 地址', placeholder: 'https://api.telegram.org（可用反代地址）' },
  server_url: { label: '服务器地址', placeholder: 'https://api.day.app 或 https://ntfy.sh' },
  device_key: { label: 'Device Key', placeholder: 'Bark App 首页显示的 Device Key', secret: true },
  topic: { label: '主题 Topic', placeholder: '在 ntfy App 中订阅的主题名称' },
  token: { label: '访问令牌 / Token', placeholder: 'PushPlus 或 ntfy 的 Token', secret: true },
  sendkey: { label: 'SendKey', placeholder: 'SCT... 或 sctp... 微信推送密钥', secret: true },
  url: { label: '回调地址', placeholder: 'https://your-server.com/api/notify-hook（POST JSON）', secret: true },
  headers: { label: '请求头 (Headers)', placeholder: '{"Authorization": "Bearer xxx"}' },
  host: { label: 'SMTP 服务器', placeholder: 'smtp.qq.com / smtp.163.com' },
  port: { label: '端口号', placeholder: '465 (SSL) 或 587' },
  ssl: { label: '使用 SSL 加密' },
  starttls: { label: 'STARTTLS 加密' },
  secret: { label: '加签 / 签名密钥', placeholder: '机器人安全设置里的签名密钥（选填）', secret: true },
  username: { label: '发件邮箱账号', placeholder: 'your_email@qq.com' },
  password: { label: 'SMTP 授权码 / 密码', placeholder: '邮箱设置里生成的授权码，非登录密码', secret: true },
  to: { label: '接收邮箱地址', placeholder: 'receiver@example.com' },
}
const labelOf = (k: string) => fieldMeta[k]?.label || k

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

// ---------------------------------------------------------------- 编辑 & 测试弹窗状态
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
  testing: false,
  testResult: null as { ok: boolean; message: string } | null,
  id: null as number | null,
  name: '',
  type: 'wecom',
  config: {} as Record<string, string>,
  nums: {} as Record<string, number | null | undefined>,
  bools: {} as Record<string, boolean>,
  events: [] as string[],
  enabled: true,
})

const currentApp = computed(() => {
  return (
    connectorApps.find((a) => a.type === edit.type) || {
      type: edit.type,
      name: notifyTypeMap[edit.type] || edit.type,
      category: 'dev' as const,
      categoryLabel: '通用连接器',
      desc: '自定义消息推送与通知桥接器。',
      guide: '请按对应渠道协议填写配置参数。',
    }
  )
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

/** 打开添加指定应用的弹窗 */
function openAddForApp(app: ConnectorApp) {
  edit.testResult = null
  const defaultName = `${app.name}通知`
  Object.assign(edit, {
    open: true,
    id: null,
    name: defaultName,
    type: app.type,
    config: {},
    nums: {},
    bools: {},
    // 默认订阅全部事件
    events: [],
    enabled: true,
  })
}

/** 打开通用创建 */
function openCreateCustom() {
  const customApp = connectorApps.find((a) => a.type === 'webhook') || connectorApps[0]
  openAddForApp(customApp)
}

/** 打开编辑已有渠道 */
function openEdit(c: Channel) {
  edit.testResult = null
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
  Object.assign(edit, {
    open: true,
    id: c.id,
    name: c.name,
    type: c.type,
    config: cfg,
    nums,
    bools,
    events: [...c.events],
    enabled: c.enabled,
  })
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

/** 测试未保存或正在配置的连接器连通性 */
async function testCurrentConfig() {
  const config = buildConfig()
  if (!config) return
  edit.testing = true
  edit.testResult = null
  try {
    const res = await testUnsavedChannel({
      type: edit.type,
      config,
      name: edit.name.trim() || currentApp.value.name,
    })
    if (res.ok) {
      edit.testResult = {
        ok: true,
        message: `测试通知已成功发送至 ${currentApp.value.name}！请打开对应应用或群聊查收确认。`,
      }
      ElMessage.success('测试成功！连接器工作正常')
    } else {
      edit.testResult = {
        ok: false,
        message: `连通失败：${res.error || '未知错误，请检查网络或填写信息是否正确'}`,
      }
      ElMessage.error('连通失败，请检查配置')
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    edit.testResult = { ok: false, message: `请求失败：${msg}` }
  } finally {
    edit.testing = false
  }
}

/** 保存连接器 */
async function save() {
  if (!edit.name.trim()) return ElMessage.warning('请填写渠道名称')
  const config = buildConfig()
  if (!config) return
  edit.saving = true
  try {
    if (edit.id) {
      await updateChannel(edit.id, {
        name: edit.name.trim(),
        config,
        events: edit.events,
        enabled: edit.enabled,
      })
      ElMessage.success('连接器配置已更新')
    } else {
      await createChannel({
        name: edit.name.trim(),
        type: edit.type,
        config,
        events: edit.events,
        enabled: edit.enabled,
      })
      ElMessage.success(`已成功接入「${currentApp.value.name}」连接器`)
    }
    edit.open = false
    await load()
  } finally {
    edit.saving = false
  }
}

/** 快捷事件预设选择 */
function setEventPreset(preset: 'all' | 'core' | 'none') {
  if (preset === 'all') {
    edit.events = []
  } else if (preset === 'core') {
    edit.events = ['order_paid', 'delivery_failed', 'stock_low', 'human_handoff', 'account_risk']
  } else {
    edit.events = ['none_placeholder']
  }
}

function isEventChecked(e: string): boolean {
  if (!edit.events.length) return true // 空数组代表全部
  return edit.events.includes(e)
}

function toggleEvent(e: string) {
  if (!edit.events.length) {
    // 原来是全选状态，取消某一个
    edit.events = meta.value.events.filter((item) => item !== e)
  } else if (edit.events.includes(e)) {
    edit.events = edit.events.filter((item) => item !== e)
    if (edit.events.length === 0) {
      // 保持至少非全选
      edit.events = ['none_placeholder']
    }
  } else {
    edit.events = edit.events.filter((item) => item !== 'none_placeholder')
    edit.events.push(e)
    if (edit.events.length === meta.value.events.length) {
      edit.events = [] // 全选以空数组保存
    }
  }
}

/** 针对已有渠道的操作 */
async function testExisting(c: Channel) {
  busy[`t-${c.id}`] = true
  try {
    const r = await testChannel(c.id)
    if (r.ok) ElMessage.success('测试消息已发送，请检查应用通知')
    else ElMessage.error(`发送失败：${r.error}`)
    await load()
  } finally {
    busy[`t-${c.id}`] = false
  }
}

async function toggleChannelEnabled(c: Channel, enabled: boolean) {
  try {
    await updateChannel(c.id, { enabled })
    c.enabled = enabled
    ElMessage.success(enabled ? '已启用该渠道通知' : '已暂停该渠道通知')
  } catch {
    /* 拦截器已处理 */
  }
}

async function remove(c: Channel) {
  await ElMessageBox.confirm(`确定要移除通知渠道「${c.name}」吗？移除后相关消息将不再发送到此应用。`, '删除确认', {
    type: 'warning',
    confirmButtonText: '确定删除',
    cancelButtonText: '取消',
  })
  await deleteChannel(c.id)
  ElMessage.success('已删除渠道')
  await load()
}
</script>

<template>
  <div class="notify-page">
    <!-- 1. 顶部 Header 导航条与搜索栏（参考参考图风格） -->
    <div class="top-nav-bar">
      <div class="tabs-group">
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'market' }"
          @click="activeTab = 'market'"
        >
          <span class="tab-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
            </svg>
          </span>
          <span>应用连接器</span>
        </button>

        <button
          class="tab-btn"
          :class="{ active: activeTab === 'connected' }"
          @click="activeTab = 'connected'"
        >
          <span class="tab-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
              <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
            </svg>
          </span>
          <span>已连接渠道</span>
          <span v-if="channels.length" class="count-pill">{{ channels.length }}</span>
        </button>
      </div>

      <div class="top-actions">
        <div class="search-wrap">
          <el-icon class="search-icon"><Search /></el-icon>
          <input
            v-model="searchQuery"
            type="text"
            class="clean-search-input"
            placeholder="搜索连接器..."
          />
          <button v-if="searchQuery" class="clear-search-btn" @click="searchQuery = ''">×</button>
        </div>

        <button class="custom-conn-btn" @click="openCreateCustom">
          <span class="plus-icon">+</span>
          <span>自定义连接器</span>
        </button>

        <button class="refresh-circle-btn" :class="{ spinning: loading }" title="刷新" @click="load">
          <el-icon><Refresh /></el-icon>
        </button>
      </div>
    </div>

    <!-- 2. 分类筛选 Pills (仅在市场 Tab 下展示) -->
    <div v-if="activeTab === 'market'" class="category-filter-bar">
      <button
        v-for="cat in categories"
        :key="cat.key"
        class="cat-chip"
        :class="{ active: selectedCategory === cat.key }"
        @click="selectedCategory = cat.key"
      >
        {{ cat.label }}
      </button>
    </div>

    <!-- 3. 应用连接器市场 Grid（双列真实软件图标卡片） -->
    <div v-if="activeTab === 'market'" v-loading="loading" class="market-view-container">
      <div v-if="!filteredConnectors.length" class="empty-search-box">
        <el-empty description="没有找到匹配的应用连接器">
          <el-button @click="searchQuery = ''; selectedCategory = 'all'">清除筛选条件</el-button>
        </el-empty>
      </div>

      <div v-else class="connector-market-grid">
        <div
          v-for="app in filteredConnectors"
          :key="app.type"
          class="connector-app-card"
          @click="openAddForApp(app)"
        >
          <!-- 左侧真实品牌图标 -->
          <div class="app-icon-wrapper">
            <ConnectorIcon :type="app.type" :size="48" />
          </div>

          <!-- 中间文本内容 -->
          <div class="app-content-body">
            <div class="app-title-row">
              <span class="app-title">{{ app.name }}</span>
              <span v-if="app.subTag" class="app-provider-pill">{{ app.subTag }}</span>
              <span v-if="getConnectedCount(app.type) > 0" class="connected-badge">
                <span class="badge-dot"></span>
                已接入 {{ getConnectedCount(app.type) }} 个
              </span>
            </div>
            <p class="app-description">{{ app.desc }}</p>
          </div>

          <!-- 右侧圆形添加按钮 -->
          <div class="card-action-side">
            <button
              class="round-plus-btn"
              title="配置并接入此应用"
              @click.stop="openAddForApp(app)"
            >
              <span class="plus-symbol">+</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 4. 已连接渠道管理 View (管理现存配置) -->
    <div v-if="activeTab === 'connected'" v-loading="loading" class="connected-view-container">
      <div v-if="!channels.length" class="empty-connected-card">
        <el-empty description="尚未配置任何通知渠道，订单、发货与风控消息将无法推送到应用">
          <button class="custom-conn-btn" @click="activeTab = 'market'">
            <span class="plus-icon">+</span>
            <span>前往应用连接器市场添加</span>
          </button>
        </el-empty>
      </div>

      <div v-else class="connected-list-grid">
        <div v-for="c in channels" :key="c.id" class="connected-channel-card">
          <div class="ch-card-header">
            <div class="ch-info-left">
              <ConnectorIcon :type="c.type" :size="38" />
              <div class="ch-names">
                <div class="ch-title-text">{{ c.name }}</div>
                <div class="ch-sub-meta">
                  <span class="type-pill">{{ notifyTypeMap[c.type] || c.type }}</span>
                  <span v-if="c.enabled" class="status-live-tag">
                    <span class="dot-green"></span> 推送生效中
                  </span>
                  <span v-else class="status-disabled-tag">已暂停</span>
                </div>
              </div>
            </div>

            <div class="ch-switch-box">
              <el-switch
                :model-value="c.enabled"
                @change="(v: string | number | boolean) => toggleChannelEnabled(c, !!v)"
              />
            </div>
          </div>

          <!-- 事件订阅列表 -->
          <div class="ch-card-events">
            <span class="events-label">触发事件：</span>
            <div class="events-tags-wrap">
              <template v-if="c.events && c.events.length && !c.events.includes('none_placeholder')">
                <span v-for="e in c.events" :key="e" class="event-tag-bubble">
                  {{ notifyEventMap[e] || e }}
                </span>
              </template>
              <span v-else-if="!c.events || !c.events.length" class="event-tag-bubble all">
                全部业务事件
              </span>
              <span v-else class="event-tag-bubble none">
                未订阅任何事件
              </span>
            </div>
          </div>

          <!-- 配置摘要 -->
          <div class="ch-card-config">
            <div v-for="(v, k) in c.config" :key="k" class="config-row-item">
              <span class="cfg-key">{{ labelOf(String(k)) }}：</span>
              <span class="cfg-val mono">{{ typeof v === 'object' ? JSON.stringify(v) : v }}</span>
            </div>
          </div>

          <!-- 最近发送失败警告 -->
          <div v-if="c.last_error" class="ch-error-alert">
            <el-icon class="err-icon"><WarningFilled /></el-icon>
            <span class="err-text">最近发送失败：{{ c.last_error }}</span>
          </div>

          <!-- 操作条 -->
          <div class="ch-card-actions">
            <button
              class="action-btn-test"
              :disabled="busy[`t-${c.id}`]"
              @click="testExisting(c)"
            >
              <el-icon v-if="busy[`t-${c.id}`]" class="is-loading"><Refresh /></el-icon>
              <el-icon v-else><Connection /></el-icon>
              <span>测试消息</span>
            </button>

            <button class="action-btn-edit" @click="openEdit(c)">
              <el-icon><Edit /></el-icon>
              <span>编辑</span>
            </button>

            <button class="action-btn-delete" @click="remove(c)">
              <el-icon><Delete /></el-icon>
              <span>删除</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 5. 连接器配置与连通测试弹窗 (Drawer / Modal) -->
    <el-dialog
      v-model="edit.open"
      :title="edit.id ? `编辑连接器 · ${edit.name}` : `接入连接器 · ${currentApp.name}${currentApp.subTag ? '（' + currentApp.subTag + '）' : ''}`"
      :width="isMobile ? '95%' : '680px'"
      :close-on-click-modal="false"
      class="connector-dialog"
    >
      <div class="dialog-inner-content">
        <!-- 引导指引条 -->
        <div class="guide-banner">
          <ConnectorIcon :type="edit.type" :size="36" />
          <div class="guide-text">
            <div class="guide-app-title">
              {{ currentApp.name }}
              <span v-if="currentApp.subTag" class="app-provider-pill">{{ currentApp.subTag }}</span>
              接入指引
            </div>
            <div class="guide-detail">{{ currentApp.guide }}</div>
          </div>
        </div>

        <el-form label-width="120px" :label-position="isMobile ? 'top' : 'right'" class="setup-form">
          <el-form-item label="渠道名称" required>
            <el-input
              v-model="edit.name"
              maxlength="64"
              placeholder="例如：运营大群通知 / 个人手机推送"
            />
          </el-form-item>

          <!-- 动态配置字段 -->
          <el-form-item
            v-for="f in fields"
            :key="`${edit.type}-${f.key}`"
            :label="labelOf(f.key)"
            :required="f.required"
          >
            <!-- 布尔类型 -->
            <el-switch
              v-if="f.kind === 'boolean'"
              :model-value="boolValue(f)"
              @update:model-value="(v: string | number | boolean) => (edit.bools[f.key] = !!v)"
            />

            <!-- 数字类型 -->
            <el-input-number
              v-else-if="f.kind === 'number'"
              :model-value="numValue(f)"
              :min="0"
              :step="1"
              :step-strictly="Number.isInteger(f.default)"
              controls-position="right"
              @update:model-value="(v: number | null | undefined) => (edit.nums[f.key] = v)"
            />

            <!-- 字符串 / 密码 / JSON -->
            <div v-else class="input-with-secret-toggle">
              <el-input
                v-model="edit.config[f.key]"
                :type="f.kind === 'json' ? 'textarea' : fieldMeta[f.key]?.secret && !showSecrets[f.key] ? 'password' : 'text'"
                :rows="f.kind === 'json' ? 3 : undefined"
                :class="{ mono: f.kind === 'json' }"
                :placeholder="placeholderOf(f)"
              />
              <button
                v-if="fieldMeta[f.key]?.secret"
                type="button"
                class="secret-toggle-btn"
                :title="showSecrets[f.key] ? '隐藏内容' : '查看明文'"
                @click="showSecrets[f.key] = !showSecrets[f.key]"
              >
                <el-icon><View v-if="!showSecrets[f.key]" /><Hide v-else /></el-icon>
              </button>
            </div>
            <div v-if="f.kind === 'json'" class="form-tip">填写 JSON 格式，留空则使用默认配置。</div>
          </el-form-item>

          <!-- 订阅事件多选组 -->
          <el-form-item label="订阅事件">
            <div class="event-picker-block">
              <div class="preset-buttons-row">
                <button
                  type="button"
                  class="preset-btn"
                  :class="{ active: !edit.events.length }"
                  @click="setEventPreset('all')"
                >
                  全部事件 (推荐)
                </button>
                <button
                  type="button"
                  class="preset-btn"
                  @click="setEventPreset('core')"
                >
                  核心订单与风控
                </button>
                <button
                  type="button"
                  class="preset-btn text-muted"
                  @click="setEventPreset('none')"
                >
                  清空
                </button>
              </div>

              <div class="event-category-grid">
                <div v-for="grp in eventGroups" :key="grp.name" class="event-group-card">
                  <div class="event-grp-title">
                    <span class="grp-icon">{{ grp.icon }}</span>
                    <span>{{ grp.name }}</span>
                  </div>
                  <div class="event-checkbox-list">
                    <label
                      v-for="e in grp.events"
                      :key="e"
                      class="custom-check-item"
                      :class="{ checked: isEventChecked(e) }"
                      @click.prevent="toggleEvent(e)"
                    >
                      <span class="checkbox-indicator">
                        <el-icon v-if="isEventChecked(e)"><Check /></el-icon>
                      </span>
                      <span class="check-label">{{ notifyEventMap[e] || e }}</span>
                    </label>
                  </div>
                </div>
              </div>
            </div>
          </el-form-item>

          <el-form-item label="启用状态">
            <el-switch v-model="edit.enabled" />
            <span class="switch-tip-text">{{ edit.enabled ? '已启用（将实时推送勾选的消息）' : '已暂停推送' }}</span>
          </el-form-item>
        </el-form>

        <!-- 实时测试结果提示条 -->
        <div v-if="edit.testResult" class="test-feedback-box" :class="{ success: edit.testResult.ok, error: !edit.testResult.ok }">
          <el-icon class="feedback-icon">
            <CircleCheck v-if="edit.testResult.ok" />
            <WarningFilled v-else />
          </el-icon>
          <div class="feedback-message">{{ edit.testResult.message }}</div>
        </div>
      </div>

      <template #footer>
        <div class="dialog-footer-row">
          <div class="footer-left">
            <el-button
              :loading="edit.testing"
              :icon="Connection"
              @click="testCurrentConfig"
            >
              测试连通性
            </el-button>
          </div>
          <div class="footer-right">
            <el-button @click="edit.open = false">取消</el-button>
            <el-button type="primary" :loading="edit.saving" @click="save">
              {{ edit.id ? '保存更新' : '立即保存并启用' }}
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.notify-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: calc(100vh - 120px);
}

/* ================= 1. 顶部 Header 导航条与搜索 ================= */
.top-nav-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 4px 0 8px;
}

.tabs-group {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--xh-fill);
  padding: 4px;
  border-radius: var(--xh-radius-pill);
  border: 1px solid var(--xh-border);
}

.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  border-radius: var(--xh-radius-pill);
  border: none;
  background: transparent;
  color: var(--xh-text-2);
  font-size: var(--xh-fs-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.tab-btn:hover {
  color: var(--xh-text);
}

.tab-btn.active {
  background: var(--xh-text);
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
}

.tab-btn .tab-icon {
  display: flex;
  align-items: center;
}

.count-pill {
  display: inline-block;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.25);
  line-height: 1.2;
}

.tab-btn:not(.active) .count-pill {
  background: var(--xh-fill-strong);
  color: var(--xh-text-2);
}

.top-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.search-wrap {
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 12px;
  color: var(--xh-muted);
  pointer-events: none;
  font-size: 14px;
}

.clean-search-input {
  width: 220px;
  height: 36px;
  padding: 0 28px 0 32px;
  border-radius: var(--xh-radius-pill);
  border: 1px solid var(--xh-border);
  background: var(--xh-card);
  color: var(--xh-text);
  font-size: var(--xh-fs-sm);
  outline: none;
  transition: all 0.2s ease;
}

.clean-search-input:focus {
  border-color: var(--xh-primary);
  box-shadow: 0 0 0 2px var(--xh-primary-soft);
  width: 260px;
}

.clear-search-btn {
  position: absolute;
  right: 10px;
  background: none;
  border: none;
  font-size: 16px;
  color: var(--xh-muted);
  cursor: pointer;
  line-height: 1;
}

.custom-conn-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 16px;
  border-radius: var(--xh-radius-pill);
  border: 1px solid var(--xh-border-strong);
  background: var(--xh-card);
  color: var(--xh-text);
  font-size: var(--xh-fs-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.custom-conn-btn:hover {
  border-color: var(--xh-primary);
  color: var(--xh-primary);
  background: var(--xh-primary-soft);
}

.custom-conn-btn .plus-icon {
  font-size: 16px;
  font-weight: 600;
}

.refresh-circle-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 1px solid var(--xh-border);
  background: var(--xh-card);
  color: var(--xh-text-2);
  cursor: pointer;
  transition: all 0.2s;
}

.refresh-circle-btn:hover {
  color: var(--xh-text);
  border-color: var(--xh-border-strong);
}

.refresh-circle-btn.spinning .el-icon {
  animation: spin 1s infinite linear;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* ================= 2. 分类 Pills ================= */
.category-filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 2px;
}

.cat-chip {
  padding: 5px 14px;
  border-radius: var(--xh-radius-pill);
  border: 1px solid transparent;
  background: transparent;
  color: var(--xh-text-2);
  font-size: var(--xh-fs-sm);
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}

.cat-chip:hover {
  background: var(--xh-fill);
  color: var(--xh-text);
}

.cat-chip.active {
  background: var(--xh-fill-strong);
  color: var(--xh-text);
  font-weight: 600;
  border-color: var(--xh-border);
}

/* ================= 3. 连接器卡片网格 ================= */
.connector-market-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

@media (max-width: 900px) {
  .connector-market-grid {
    grid-template-columns: 1fr;
  }
}

.connector-app-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.connector-app-card:hover {
  border-color: var(--xh-primary-border);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.06);
  transform: translateY(-1px);
}

.app-icon-wrapper {
  flex-shrink: 0;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.22s cubic-bezier(0.16, 1, 0.3, 1);
}

.connector-app-card:hover .app-icon-wrapper {
  transform: scale(1.05);
}

.app-content-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.app-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.app-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--xh-text);
}

.app-provider-pill {
  font-size: 11px;
  font-weight: 500;
  padding: 1px 7px;
  border-radius: 4px;
  background: var(--xh-fill-strong);
  color: var(--xh-text-2);
  border: 1px solid var(--xh-border);
}

.connected-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--xh-success);
  background: var(--xh-primary-soft);
  padding: 1px 8px;
  border-radius: 10px;
  font-weight: 500;
}

.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--xh-success);
}

.app-description {
  margin: 0;
  font-size: 13px;
  color: var(--xh-text-2);
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-action-side {
  flex-shrink: 0;
  margin-left: 4px;
}

.round-plus-btn {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 1px solid var(--xh-border);
  background: var(--xh-fill);
  color: var(--xh-text);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;
}

.round-plus-btn .plus-symbol {
  font-size: 20px;
  font-weight: 400;
  line-height: 1;
  margin-top: -1px;
}

.round-plus-btn:hover {
  background: var(--xh-primary-soft);
  border-color: var(--xh-primary-border);
  color: var(--xh-primary);
  transform: scale(1.08);
}

.empty-search-box {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: 12px;
  padding: 40px 16px;
  text-align: center;
}

/* ================= 4. 已连接渠道视图 ================= */
.connected-list-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}

.connected-channel-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: 12px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.ch-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.ch-info-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.ch-names {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ch-title-text {
  font-size: 15px;
  font-weight: 600;
  color: var(--xh-text);
}

.ch-sub-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.type-pill {
  background: var(--xh-fill-strong);
  color: var(--xh-text-2);
  padding: 1px 6px;
  border-radius: 4px;
}

.status-live-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--xh-success);
}

.status-disabled-tag {
  color: var(--xh-muted);
}

.dot-green {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--xh-success);
}

.ch-card-events {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
}

.events-label {
  color: var(--xh-muted);
  flex-shrink: 0;
  margin-top: 2px;
}

.events-tags-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.event-tag-bubble {
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  color: var(--xh-text-2);
  padding: 1px 7px;
  border-radius: 4px;
}

.event-tag-bubble.all {
  background: var(--xh-primary-soft);
  border-color: var(--xh-primary-border);
  color: var(--xh-primary);
  font-weight: 500;
}

.event-tag-bubble.none {
  color: var(--xh-muted);
}

.ch-card-config {
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  border-radius: 6px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.config-row-item {
  display: flex;
  align-items: center;
  font-size: 12px;
  overflow: hidden;
}

.cfg-key {
  color: var(--xh-muted);
  flex-shrink: 0;
}

.cfg-val {
  color: var(--xh-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ch-error-alert {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 6px;
  background: #fff1f0;
  border: 1px solid #ffa39e;
  color: var(--xh-danger);
  font-size: 12px;
}

.ch-card-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: auto;
  padding-top: 4px;
}

.action-btn-test,
.action-btn-edit,
.action-btn-delete {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.action-btn-test {
  background: var(--xh-primary-soft);
  border: 1px solid var(--xh-primary-border);
  color: var(--xh-primary);
}
.action-btn-test:hover {
  background: var(--xh-primary);
  color: #fff;
}

.action-btn-edit {
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  color: var(--xh-text);
}
.action-btn-edit:hover {
  border-color: var(--xh-border-strong);
  background: var(--xh-fill-strong);
}

.action-btn-delete {
  background: transparent;
  border: 1px solid transparent;
  color: var(--xh-danger);
  margin-left: auto;
}
.action-btn-delete:hover {
  background: #fff1f0;
  border-color: #ffa39e;
}

.empty-connected-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: 12px;
  padding: 48px 16px;
  text-align: center;
}

/* ================= 5. 配置弹窗样式 ================= */
.guide-banner {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 16px;
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  border-radius: 10px;
  margin-bottom: 20px;
}

.guide-text {
  flex: 1;
}

.guide-app-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 14px;
  color: var(--xh-text);
  margin-bottom: 3px;
}

.guide-detail {
  font-size: 12px;
  color: var(--xh-text-2);
  line-height: 1.5;
}

.input-with-secret-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
}

.secret-toggle-btn {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  border: 1px solid var(--xh-border);
  background: var(--xh-fill);
  color: var(--xh-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.secret-toggle-btn:hover {
  color: var(--xh-text);
  border-color: var(--xh-border-strong);
}

.form-tip {
  font-size: 12px;
  color: var(--xh-muted);
  margin-top: 4px;
}

.event-picker-block {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

.preset-buttons-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.preset-btn {
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 12px;
  border: 1px solid var(--xh-border);
  background: var(--xh-card);
  color: var(--xh-text-2);
  cursor: pointer;
  transition: all 0.15s;
}

.preset-btn:hover {
  border-color: var(--xh-primary-border);
  color: var(--xh-primary);
}

.preset-btn.active {
  background: var(--xh-primary);
  border-color: var(--xh-primary);
  color: #fff;
}

.event-category-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

@media (max-width: 600px) {
  .event-category-grid {
    grid-template-columns: 1fr;
  }
}

.event-group-card {
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  border-radius: 8px;
  padding: 10px 12px;
}

.event-grp-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--xh-text);
  margin-bottom: 8px;
}

.event-checkbox-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.custom-check-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 6px;
  border-radius: 4px;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  color: var(--xh-text-2);
  transition: background 0.12s;
}

.custom-check-item:hover {
  background: rgba(0, 0, 0, 0.03);
}

.custom-check-item.checked {
  color: var(--xh-text);
  font-weight: 500;
}

.checkbox-indicator {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  border: 1px solid var(--xh-border-strong);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--xh-card);
  color: #fff;
  font-size: 11px;
}

.custom-check-item.checked .checkbox-indicator {
  background: var(--xh-primary);
  border-color: var(--xh-primary);
}

.switch-tip-text {
  margin-left: 10px;
  font-size: 12px;
  color: var(--xh-muted);
}

.test-feedback-box {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  margin-top: 14px;
}

.test-feedback-box.success {
  background: var(--xh-primary-soft);
  border: 1px solid var(--xh-primary-border);
  color: var(--xh-success);
}

.test-feedback-box.error {
  background: #fff1f0;
  border: 1px solid #ffa39e;
  color: var(--xh-danger);
}

.dialog-footer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
</style>
