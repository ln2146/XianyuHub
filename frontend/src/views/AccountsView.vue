<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, Plus, Refresh, Upload } from '@element-plus/icons-vue'
import QRCode from 'qrcode'
import {
  addGrant,
  deleteAccount,
  importCookies,
  listGrants,
  removeGrant,
  listRiskEvents,
  probeAccount,
  qrPoll,
  qrStart,
  resolveRisk,
  updateAccount,
  type Account,
  type AccountGrant,
  type AccountSettings,
  type QrStatus,
  type RiskEvent,
} from '@/api/account'
import { getImStatus, type ImStatus } from '@/api/message'
import { listBindings } from '@/api/order'
import { listUsers, type UserOut } from '@/api/system'
import StatusTag from '@/components/StatusTag.vue'
import { useAccountsStore } from '@/stores/accounts'
import { useAuthStore } from '@/stores/auth'
import { useMobile } from '@/composables/useMobile'
import { accountStatusMap, fmtTime, roleMap } from '@/utils/format'

const store = useAccountsStore()
const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')
const isMobile = useMobile()
const loading = ref(false)
const im = ref<ImStatus>({ running: false, accounts: {} })
const busy = reactive<Record<string, boolean>>({})

async function load() {
  loading.value = true
  try {
    await store.load(true)
    im.value = await getImStatus().catch(() => ({ running: false, accounts: {} }))
  } finally {
    loading.value = false
  }
}
onMounted(load)

function imConnected(id: number) {
  return !!im.value.accounts[String(id)]?.connected
}

function healthColor(h: number) {
  if (h >= 80) return 'var(--xh-success)'
  if (h >= 50) return 'var(--xh-warning)'
  return 'var(--xh-danger)'
}

async function withBusy(key: string, fn: () => Promise<void>) {
  busy[key] = true
  try {
    await fn()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[key] = false
  }
}

function probe(a: Account) {
  return withBusy(`probe-${a.id}`, async () => {
    const r = await probeAccount(a.id)
    if (r.ok) ElMessage.success('登录状态正常')
    else ElMessage.warning(`登录检查未通过，当前状态：${accountStatusMap[r.status]?.label || r.status}`)
    await load()
  })
}

async function quickEditRemark(a: Account) {
  try {
    const { value } = await ElMessageBox.prompt('请输入账号备注名称（方便区分多店铺/矩阵）：', '修改账号备注', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: a.remark || '',
      inputPlaceholder: '例如：数码专营店 / 主账号',
      inputValidator: (val) => {
        if (val && val.length > 128) return '备注长度不能超过 128 个字符'
        return true
      },
    })
    const remark = (value ?? '').trim()
    await updateAccount(a.id, { remark })
    ElMessage.success('备注已更新')
    await store.load(true)
  } catch (err: any) {
    if (err !== 'cancel' && err !== 'close') {
      ElMessage.error(err?.message || '更新失败')
    }
  }
}

async function resolve(a: Account) {
  await ElMessageBox.confirm(
    '请确认已在闲鱼 App / 网页完成滑块、短信或人脸等验证。确认后账号将恢复为正常状态，自动化任务会重新开始执行。',
    '标记已完成验证',
    { type: 'warning', confirmButtonText: '我已处理' },
  )
  await withBusy(`resolve-${a.id}`, async () => {
    const r = await resolveRisk(a.id)
    ElMessage.success(`已恢复，当前状态：${accountStatusMap[r.status]?.label || r.status}`)
    await load()
  })
}

async function toggleEnabled(a: Account) {
  const enable = a.status === 'disabled'
  await ElMessageBox.confirm(enable ? '启用后将恢复该账号的所有自动化任务。' : '停用后该账号不再执行任何自动操作。', enable ? '启用账号' : '停用账号', {
    type: 'warning',
  })
  await withBusy(`enable-${a.id}`, async () => {
    await updateAccount(a.id, { enabled: enable })
    ElMessage.success(enable ? '已启用' : '已停用')
    await load()
  })
}

async function remove(a: Account) {
  await ElMessageBox.confirm(
    `将删除账号「${a.nickname || a.unb}」及其本地会话、商品、订单数据（不影响闲鱼上的真实数据），此操作不可恢复。`,
    '删除账号',
    { type: 'error', confirmButtonText: '删除', confirmButtonClass: 'el-button--danger' },
  )
  await withBusy(`del-${a.id}`, async () => {
    await deleteAccount(a.id)
    ElMessage.success('已删除')
    await load()
  })
}

// ---------------------------------------------------------------- 扫码登录
const qr = reactive({
  open: false,
  proxy: '',
  id: '',
  image: '',
  status: '' as QrStatus | '',
  message: '',
  verifyUrl: '',
  starting: false,
})
let qrTimer: number | undefined

const qrStatusText: Record<string, string> = {
  NEW: '请使用闲鱼 App 扫描二维码',
  SCANED: '已扫码，请在手机上确认登录',
  CONFIRMED: '已确认，正在登录…',
  EXPIRED: '二维码已过期，请刷新',
  CANCELED: '已在手机上取消登录',
  NEED_VERIFY: '需要身份验证',
  SUCCESS: '登录成功',
  ERROR: '登录失败',
}

function stopQrPoll() {
  window.clearTimeout(qrTimer)
  qrTimer = undefined
}

async function startQr() {
  stopQrPoll()
  qr.starting = true
  qr.status = ''
  qr.message = ''
  qr.verifyUrl = ''
  qr.image = ''
  try {
    const r = await qrStart(qr.proxy.trim() || null)
    qr.id = r.qr_id
    qr.image = await QRCode.toDataURL(r.qr_content, { width: 220, margin: 1 })
    qr.status = 'NEW'
    scheduleQrPoll()
  } finally {
    qr.starting = false
  }
}

function scheduleQrPoll() {
  stopQrPoll()
  qrTimer = window.setTimeout(pollQr, 2000)
}

async function pollQr() {
  if (!qr.open || !qr.id) return
  try {
    const r = await qrPoll(qr.id)
    qr.status = r.status
    qr.message = r.message || ''
    qr.verifyUrl = r.verify_url || ''
    if (r.status === 'SUCCESS') {
      ElMessage.success('扫码登录成功，账号已添加')
      qr.open = false
      await load()
      return
    }
    // 过期 / 取消 / 出错 / 需要验证 时停止轮询
    if (['EXPIRED', 'CANCELED', 'ERROR', 'NEED_VERIFY'].includes(r.status)) return
    scheduleQrPoll()
  } catch (e) {
    qr.status = 'ERROR'
    qr.message = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail || '轮询失败'
  }
}

function openQr() {
  qr.open = true
  qr.proxy = ''
  qr.id = ''
  qr.image = ''
  qr.status = ''
}

function closeQr() {
  stopQrPoll()
  qr.id = ''
}

// ---------------------------------------------------------------- 导入 Cookie
const cookie = reactive({ open: false, cookies: '', proxy: '', verify: true, saving: false })

function openCookie() {
  Object.assign(cookie, { open: true, cookies: '', proxy: '', verify: true })
}

async function submitCookie() {
  if (!cookie.cookies.trim()) {
    ElMessage.warning('请粘贴 Cookie')
    return
  }
  cookie.saving = true
  try {
    const acc = await importCookies({ cookies: cookie.cookies.trim(), proxy: cookie.proxy.trim() || null, verify: cookie.verify })
    ElMessage.success(`已导入账号 ${acc.nickname || acc.unb}`)
    cookie.open = false
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    cookie.saving = false
  }
}

// ---------------------------------------------------------------- 重新登录
const relogin = reactive({
  open: false,
  account: null as Account | null,
  tab: 'qr' as 'qr' | 'cookie',
  // 扫码
  qrId: '',
  qrImage: '',
  qrStatus: '' as QrStatus | '',
  qrMessage: '',
  qrVerifyUrl: '',
  qrStarting: false,
  // Cookie 导入
  cookies: '',
  proxy: '',
  useExistingProxy: true,
  verify: true,
  submitting: false,
})
let reloginTimer: number | undefined

function isSessionExpired(row: any): boolean {
  if (!row) return false
  if (row.status === 'need_login' || row.status === 'inactive') return true
  const err = row.last_error || ''
  return (
    err.includes('FAIL_SYS_SESSION_EXPIRED') ||
    err.includes('FAIL_SYS_LOGIN') ||
    err.includes('FAIL_SYS_USER_NOT_LOGIN') ||
    err.toLowerCase().includes('session expired') ||
    err.includes('登录已失效') ||
    err.includes('未登录')
  )
}

function openReLogin(a: Account) {
  stopReLoginQrPoll()
  relogin.account = a
  relogin.open = true
  relogin.tab = 'qr'
  relogin.cookies = ''
  relogin.proxy = ''
  relogin.useExistingProxy = !!a.has_proxy
  relogin.verify = true
  // 自动开始生成登录二维码
  startReLoginQr()
}

async function startReLoginQr() {
  const a = relogin.account
  if (!a) return
  stopReLoginQrPoll()
  relogin.qrStarting = true
  relogin.qrId = ''
  relogin.qrImage = ''
  relogin.qrStatus = 'NEW'
  relogin.qrMessage = '正在生成二维码...'
  relogin.qrVerifyUrl = ''
  try {
    const res = await qrStart(null, a.id)
    relogin.qrId = res.qr_id
    relogin.qrImage = await QRCode.toDataURL(res.qr_content, { width: 232, margin: 1 })
    relogin.qrStatus = 'NEW'
    relogin.qrMessage = '请使用闲鱼 App 扫码登录'
    scheduleReLoginQrPoll(1500)
  } catch {
    relogin.qrStatus = 'ERROR'
    relogin.qrMessage = '生成二维码失败，请重试'
  } finally {
    relogin.qrStarting = false
  }
}

async function pollReLoginQr() {
  if (!relogin.open || !relogin.qrId) return
  try {
    const res = await qrPoll(relogin.qrId)
    relogin.qrStatus = res.status
    relogin.qrMessage = res.message || ''
    relogin.qrVerifyUrl = res.verify_url || ''
    if (res.status === 'SUCCESS') {
      ElMessage.success(`账号「${relogin.account?.nickname || relogin.account?.unb}」重新登录成功！`)
      closeReLogin()
      await load()
      return
    }
    if (['EXPIRED', 'CANCELED', 'ERROR'].includes(res.status)) {
      return
    }
    const nextDelay = res.status === 'SCANED' ? 1000 : 2000
    scheduleReLoginQrPoll(nextDelay)
  } catch {
    relogin.qrStatus = 'ERROR'
    relogin.qrMessage = '轮询状态失败'
  }
}

function scheduleReLoginQrPoll(ms: number) {
  stopReLoginQrPoll()
  reloginTimer = window.setTimeout(pollReLoginQr, ms)
}

function stopReLoginQrPoll() {
  if (reloginTimer !== undefined) {
    window.clearTimeout(reloginTimer)
    reloginTimer = undefined
  }
}

function closeReLogin() {
  stopReLoginQrPoll()
  relogin.open = false
  relogin.qrId = ''
  relogin.qrImage = ''
  relogin.qrStatus = ''
}

async function submitReLoginCookie() {
  const a = relogin.account
  if (!a) return
  if (!relogin.cookies.trim()) {
    ElMessage.warning('请粘贴新 Cookie')
    return
  }
  relogin.submitting = true
  try {
    const proxyVal = relogin.useExistingProxy ? null : relogin.proxy.trim() || null
    const acc = await importCookies({
      cookies: relogin.cookies.trim(),
      proxy: proxyVal,
      verify: relogin.verify,
      account_id: a.id,
    })
    ElMessage.success(`账号「${acc.nickname || acc.unb}」登录态已恢复！`)
    closeReLogin()
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    relogin.submitting = false
  }
}

// ---------------------------------------------------------------- 账号设置
const settings = reactive({
  open: false,
  saving: false,
  account: null as Account | null,
  remark: '',
  proxy: '',
  clearProxy: false,
  form: {} as AccountSettings,
  workAllDay: true,
  workStart: '09:00',
  workEnd: '23:00',
})

function openSettings(a: Account) {
  settings.account = a
  settings.remark = a.remark
  settings.proxy = ''
  settings.clearProxy = false
  settings.form = { ...a.settings }
  const wh = a.settings.work_hours
  settings.workAllDay = !wh
  if (wh && wh.includes('-')) {
    const [s, e] = wh.split('-')
    settings.workStart = s ?? '09:00'
    settings.workEnd = e ?? '23:00'
  }
  settings.open = true
  loadBindingCount(a)
}

/** 该账号可用的商品关联数量；null 表示未知（非本人账号或加载失败），不提示 */
const bindingCount = ref<number | null>(null)

async function loadBindingCount(a: Account) {
  bindingCount.value = null
  // 关联属于账号所有者，只有本人账号才能准确判断
  if (a.owner_id !== auth.user?.id) return
  try {
    const list = await listBindings()
    bindingCount.value = list.filter((b) => b.account_id === null || b.account_id === a.id).length
  } catch {
    bindingCount.value = null
  }
}

async function saveSettings() {
  const a = settings.account
  if (!a) return
  const f = settings.form
  if (f.reply_delay_max < f.reply_delay_min) {
    ElMessage.warning('最大回复延迟不能小于最小延迟')
    return
  }
  const body = {
    remark: settings.remark,
    settings: {
      ...f,
      work_hours: settings.workAllDay ? null : `${settings.workStart}-${settings.workEnd}`,
      default_reply: f.default_reply?.trim() ? f.default_reply : null,
    },
    proxy: settings.clearProxy ? '' : settings.proxy.trim() || undefined,
  }
  settings.saving = true
  try {
    await updateAccount(a.id, body)
    ElMessage.success('设置已保存')
    settings.open = false
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    settings.saving = false
  }
}

const automationOn = computed(() => {
  const f = settings.form
  return f.auto_reply || f.auto_delivery || f.auto_polish || f.auto_rate
})

// ---------------------------------------------------------------- 风控记录
const risk = reactive({ open: false, loading: false, list: [] as RiskEvent[], account: null as Account | null })

async function openRisk(a: Account) {
  risk.account = a
  risk.open = true
  risk.loading = true
  try {
    risk.list = await listRiskEvents(a.id)
  } finally {
    risk.loading = false
  }
}

// ---------------------------------------------------------------- 授权（仅管理员）
const grant = reactive({
  open: false,
  loading: false,
  adding: false,
  account: null as Account | null,
  list: [] as AccountGrant[],
  users: [] as UserOut[],
  userId: null as number | null,
})

async function openGrants(a: Account) {
  Object.assign(grant, { open: true, loading: true, account: a, list: [], userId: null })
  try {
    const [list, users] = await Promise.all([listGrants(a.id), listUsers()])
    if (grant.account?.id !== a.id) return
    grant.list = list
    grant.users = users
  } catch {
    /* 拦截器已提示 */
  } finally {
    grant.loading = false
  }
}

/** 可选用户：排除账号所有者与已授权用户；管理员本身可见全部账号，无需授权 */
const grantOptions = computed(() => {
  const granted = new Set(grant.list.map((g) => g.user_id))
  return grant.users
    .filter((u) => u.id !== grant.account?.owner_id && !granted.has(u.id))
    .map((u) => ({
      ...u,
      disabled: u.role === 'admin' || !u.is_active,
      hint: u.role === 'admin' ? '管理员已可查看全部账号' : !u.is_active ? '已停用' : roleMap[u.role] || u.role,
    }))
})
const ownerName = computed(() => {
  const id = grant.account?.owner_id
  return grant.users.find((u) => u.id === id)?.username || (id ? `#${id}` : '-')
})

async function submitGrant() {
  const a = grant.account
  if (!a || !grant.userId) return
  grant.adding = true
  try {
    await addGrant(a.id, grant.userId)
    ElMessage.success('已授权')
    grant.userId = null
    grant.list = await listGrants(a.id)
  } catch {
    /* 拦截器已提示 */
  } finally {
    grant.adding = false
  }
}

async function revokeGrant(g: AccountGrant) {
  const a = grant.account
  if (!a) return
  try {
    await ElMessageBox.confirm(`取消「${g.username}」对该账号的授权？`, '取消授权', { type: 'warning' })
  } catch {
    return
  }
  await withBusy(`grant-${g.user_id}`, async () => {
    await removeGrant(a.id, g.user_id)
    grant.list = grant.list.filter((x) => x.user_id !== g.user_id)
    ElMessage.success('已取消授权')
  })
}

onBeforeUnmount(() => {
  stopQrPoll()
  stopReLoginQrPoll()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>账号配置</h2>
      </div>
      <div class="toolbar">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button :icon="Upload" @click="openCookie">导入 Cookie</el-button>
        <el-button type="primary" :icon="Plus" @click="openQr">扫码登录</el-button>
      </div>
    </div>

    <el-alert v-if="!im.running" type="info" show-icon :closable="false" title="消息服务未运行：收发消息、自动回复和自动发货暂不可用（请检查后端 worker 配置）。" />

    <el-card shadow="never">
      <div class="table-wrap">
        <el-table v-loading="loading" :data="store.list" empty-text="还没有账号，点击右上角「扫码登录」添加">
          <el-table-column label="账号" min-width="220">
            <template #default="{ row }">
              <div class="acc">
                <el-avatar :size="36" :src="row.avatar || undefined">{{ (row.nickname || row.unb).slice(0, 1) }}</el-avatar>
                <div class="acc-info">
                  <div class="acc-name">{{ row.nickname || row.unb }}</div>
                  <div class="acc-remark-row">
                    <span
                      class="remark-clickable"
                      :title="row.remark ? '点击修改备注' : '点击添加备注'"
                      @click="quickEditRemark(row as Account)"
                    >
                      <span class="remark-text">{{ row.remark || '点击添加备注' }}</span>
                      <el-icon class="remark-edit-icon"><Edit /></el-icon>
                    </span>
                    <el-tag v-if="row.has_proxy" size="small" effect="plain" class="ml">代理</el-tag>
                  </div>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <StatusTag :value="row.status" :map="accountStatusMap" />
              <div v-if="row.status === 'cooldown' && row.cooldown_until" class="muted small">至 {{ fmtTime(row.cooldown_until) }}</div>
            </template>
          </el-table-column>
          <el-table-column label="健康度" width="150">
            <template #default="{ row }">
              <el-progress :percentage="row.health_score" :color="healthColor(row.health_score)" :stroke-width="8" />
              <el-tooltip v-if="row.strikes" content="触发平台限制的累计次数，次数越多，每次暂停保护的时间越长" placement="top">
                <div class="muted small">异常次数 {{ row.strikes }}</div>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="消息连接" width="90">
            <template #default="{ row }">
              <el-tag :type="imConnected(row.id) ? 'success' : 'info'" size="small">{{ imConnected(row.id) ? '在线' : '离线' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="自动化" min-width="150">
            <template #default="{ row }">
              <div class="flags">
                <el-tag size="small" :type="row.settings.auto_reply ? 'success' : 'info'" effect="plain">回复{{ row.settings.auto_reply ? '开' : '关' }}</el-tag>
                <el-tag size="small" :type="row.settings.auto_delivery ? 'success' : 'info'" effect="plain">发货{{ row.settings.auto_delivery ? '开' : '关' }}</el-tag>
                <el-tag size="small" :type="row.settings.auto_polish ? 'success' : 'info'" effect="plain">擦亮{{ row.settings.auto_polish ? '开' : '关' }}</el-tag>
                <el-tag size="small" effect="plain">AI {{ { off: '关', suggest: '建议', auto: '自动' }[row.settings.ai_mode as string] }}</el-tag>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="最近检查 / 错误" min-width="190">
            <template #default="{ row }">
              <div class="small">{{ fmtTime(row.last_probe_at) }}</div>
              <div v-if="isSessionExpired(row)" class="session-expired-hint">
                <el-tag size="small" type="danger" effect="plain" class="expired-tag">登录已失效</el-tag>
                <el-link type="danger" :underline="false" class="small relogin-link" @click="openReLogin(row as Account)">重新登录</el-link>
              </div>
              <el-tooltip v-if="row.last_error" :content="row.last_error" placement="top">
                <div class="small err ellipsis">{{ row.last_error }}</div>
              </el-tooltip>
              <el-link v-if="row.punish_url" :href="row.punish_url" target="_blank" type="danger" class="small">打开验证页面</el-link>
            </template>
          </el-table-column>
          <el-table-column label="操作" :width="isMobile ? 120 : 360" :fixed="isMobile ? undefined : 'right'">
            <template #default="{ row }">
              <div class="ops">
                <el-button
                  size="small"
                  :type="isSessionExpired(row) ? 'danger' : 'warning'"
                  plain
                  @click="openReLogin(row as Account)"
                >重新登录</el-button>
                <el-button size="small" type="primary" plain @click="openSettings(row as Account)">设置</el-button>
                <el-tooltip content="用一次只读请求确认账号仍处于登录状态" placement="top">
                  <el-button size="small" :loading="busy[`probe-${row.id}`]" @click="probe(row as Account)">检查登录</el-button>
                </el-tooltip>
                <el-button
                  v-if="row.status === 'circuit_open' || row.status === 'cooldown'"
                  size="small"
                  type="warning"
                  :loading="busy[`resolve-${row.id}`]"
                  @click="resolve(row as Account)"
                >我已完成验证</el-button>
                <el-dropdown trigger="click">
                  <el-button size="small">更多</el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item @click="openReLogin(row as Account)">重新登录</el-dropdown-item>
                      <el-dropdown-item @click="openRisk(row as Account)">风控记录</el-dropdown-item>
                      <el-dropdown-item v-if="isAdmin" @click="openGrants(row as Account)">授权</el-dropdown-item>
                      <el-dropdown-item @click="toggleEnabled(row as Account)">{{ row.status === 'disabled' ? '启用账号' : '停用账号' }}</el-dropdown-item>
                      <el-dropdown-item divided @click="remove(row as Account)"><span class="err">删除账号</span></el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <!-- 扫码登录 -->
    <el-dialog v-model="qr.open" title="扫码登录" width="420px" @closed="closeQr">
      <div class="qr-box">
        <template v-if="!qr.id">
          <el-form label-position="top" class="full">
            <el-form-item label="代理（可选）">
              <el-input v-model="qr.proxy" placeholder="http://user:pass@host:port 或 socks5://…" />
            </el-form-item>
          </el-form>
          <el-button type="primary" :loading="qr.starting" @click="startQr">生成二维码</el-button>
        </template>
        <template v-else>
          <div class="qr-img" :class="{ dim: ['EXPIRED', 'CANCELED', 'ERROR'].includes(qr.status) }">
            <img v-if="qr.image" :src="qr.image" alt="登录二维码" />
          </div>
          <div class="qr-status" :class="qr.status">{{ qrStatusText[qr.status] || qr.status }}</div>
          <div v-if="qr.message && qr.status !== 'NEW'" class="muted small">{{ qr.message }}</div>
          <el-alert v-if="qr.status === 'NEED_VERIFY'" type="warning" :closable="false" class="mt">
            <div>闲鱼要求进行身份验证（人脸 / 短信），请在浏览器中打开以下链接完成验证：</div>
            <el-link v-if="qr.verifyUrl" :href="qr.verifyUrl" target="_blank" type="primary">打开验证页面</el-link>
            <div class="mt-s"><el-button size="small" type="primary" @click="pollQr">我已完成验证，继续检测</el-button></div>
          </el-alert>
          <el-button v-if="['EXPIRED', 'CANCELED', 'ERROR'].includes(qr.status)" type="primary" class="mt" :loading="qr.starting" @click="startQr">刷新二维码</el-button>
        </template>
      </div>
    </el-dialog>

    <!-- 导入 Cookie -->
    <el-dialog v-model="cookie.open" title="导入 Cookie" width="560px">
      <el-form label-position="top">
        <el-form-item label="Cookie" required>
          <el-input v-model="cookie.cookies" type="textarea" :rows="6" placeholder="粘贴 goofish.com Cookie 字符串或 JSON（需含 unb、cookie2、_m_h5_tk）" />
        </el-form-item>
        <el-form-item label="代理（可选）">
          <el-input v-model="cookie.proxy" placeholder="http://user:pass@host:port" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="cookie.verify">导入前检查登录状态（推荐）</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="cookie.open = false">取消</el-button>
        <el-button type="primary" :loading="cookie.saving" @click="submitCookie">导入</el-button>
      </template>
    </el-dialog>

    <!-- 重新登录弹窗 -->
    <el-dialog
      v-model="relogin.open"
      :title="`重新登录 · ${relogin.account?.nickname || relogin.account?.unb || ''}`"
      width="540px"
      destroy-on-close
      @closed="closeReLogin"
    >
      <div class="relogin-dialog-content">
        <!-- 账号上下文横幅 -->
        <div class="relogin-account-banner">
          <el-avatar :size="42" :src="relogin.account?.avatar || undefined">
            {{ (relogin.account?.nickname || relogin.account?.unb || 'X').slice(0, 1) }}
          </el-avatar>
          <div class="relogin-acc-meta">
            <div class="relogin-acc-name">
              <span>{{ relogin.account?.nickname || relogin.account?.unb }}</span>
              <el-tag size="small" type="info" effect="plain">ID: {{ relogin.account?.unb }}</el-tag>
              <el-tag v-if="relogin.account?.has_proxy" size="small" type="success" effect="plain">已配代理</el-tag>
            </div>
            <div class="relogin-acc-desc muted small">
              重新登录成功后将直接恢复该账号的全部业务配置、商品关联与自动化任务，无需重新创建。
            </div>
          </div>
        </div>

        <el-tabs v-model="relogin.tab" class="relogin-tabs">
          <!-- 扫码重新登录 -->
          <el-tab-pane label="闲鱼 App 扫码" name="qr">
            <div class="qr-box relogin-qr-box">
              <template v-if="relogin.qrStarting && !relogin.qrImage">
                <div class="qr-loading-box">
                  <el-icon class="is-loading" :size="32"><Refresh /></el-icon>
                  <div class="mt-s muted small">正在获取二维码...</div>
                </div>
              </template>
              <template v-else>
                <div class="qr-img" :class="{ dim: ['EXPIRED', 'CANCELED', 'ERROR'].includes(relogin.qrStatus) }">
                  <img v-if="relogin.qrImage" :src="relogin.qrImage" alt="登录二维码" />
                </div>
                <div class="qr-status" :class="relogin.qrStatus">
                  {{ qrStatusText[relogin.qrStatus] || relogin.qrStatus }}
                </div>
                <div v-if="relogin.qrMessage && relogin.qrStatus !== 'NEW'" class="muted small mt-s">
                  {{ relogin.qrMessage }}
                </div>
                <el-alert v-if="relogin.qrStatus === 'NEED_VERIFY'" type="warning" :closable="false" class="mt full">
                  <div>闲鱼要求进行身份验证（人脸 / 短信），请在浏览器中打开链接完成验证：</div>
                  <el-link v-if="relogin.qrVerifyUrl" :href="relogin.qrVerifyUrl" target="_blank" type="primary">打开验证页面</el-link>
                  <div class="mt-s"><el-button size="small" type="primary" @click="pollReLoginQr">我已完成验证，继续检测</el-button></div>
                </el-alert>
                <div class="relogin-qr-actions mt">
                  <el-button
                    type="primary"
                    :loading="relogin.qrStarting"
                    @click="startReLoginQr"
                  >
                    {{ ['EXPIRED', 'CANCELED', 'ERROR'].includes(relogin.qrStatus) ? '刷新二维码' : '重新生成二维码' }}
                  </el-button>
                </div>
                <div v-if="relogin.account?.has_proxy" class="relogin-proxy-tip muted small mt-s">
                  💡 系统将自动使用此账号绑定的专属代理进行扫码握手
                </div>
              </template>
            </div>
          </el-tab-pane>

          <!-- 导入 Cookie -->
          <el-tab-pane label="导入新 Cookie" name="cookie">
            <el-form label-position="top" class="relogin-cookie-form">
              <el-form-item label="最新 Cookie 字符串或 JSON" required>
                <el-input
                  v-model="relogin.cookies"
                  type="textarea"
                  :rows="5"
                  placeholder="粘贴 goofish.com 最新的 Cookie 字符串或导出的 JSON（需含 unb、cookie2、_m_h5_tk）"
                />
              </el-form-item>

              <el-form-item v-if="relogin.account?.has_proxy" label="代理设置">
                <el-checkbox v-model="relogin.useExistingProxy">
                  沿用该账号当前配置的专属代理（推荐）
                </el-checkbox>
                <el-input
                  v-if="!relogin.useExistingProxy"
                  v-model="relogin.proxy"
                  class="mt-s"
                  placeholder="留空表示直连，或填写 http://user:pass@host:port"
                />
              </el-form-item>
              <el-form-item v-else label="代理（可选）">
                <el-input v-model="relogin.proxy" placeholder="http://user:pass@host:port 或 socks5://…" />
              </el-form-item>

              <el-form-item>
                <el-checkbox v-model="relogin.verify">更新前校验登录状态（推荐）</el-checkbox>
              </el-form-item>

              <div class="relogin-form-foot">
                <el-button @click="closeReLogin">取消</el-button>
                <el-button
                  type="primary"
                  :loading="relogin.submitting"
                  @click="submitReLoginCookie"
                >更新并重新登录</el-button>
              </div>
            </el-form>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-dialog>

    <!-- 账号设置 -->
    <el-drawer v-model="settings.open" :title="`账号设置 · ${settings.account?.nickname || ''}`" size="560px" destroy-on-close>
      <el-alert type="warning" show-icon :closable="false" class="mb">
        <template #title>自动化默认全部关闭</template>
        开启自动回复 / 自动发货 / 自动擦亮后，系统将以你的账号身份对外发送消息或执行操作。请先在「消息中心 → 试运行」中确认回复效果，再逐项开启。
      </el-alert>
      <el-form label-position="top" class="settings-form">
        <el-divider content-position="left">基本信息</el-divider>
        <el-form-item label="备注">
          <el-input v-model="settings.remark" maxlength="128" placeholder="例如：数码店 / 小号" />
        </el-form-item>
        <el-form-item label="代理">
          <el-input v-model="settings.proxy" :disabled="settings.clearProxy" :placeholder="settings.account?.has_proxy ? '已设置代理，留空表示不修改' : '未设置，留空表示直连'" />
          <el-checkbox v-if="settings.account?.has_proxy" v-model="settings.clearProxy">清除代理</el-checkbox>
        </el-form-item>

        <el-divider content-position="left">消息</el-divider>
        <el-form-item label="自动回复总开关">
          <el-switch v-model="settings.form.auto_reply" />
        </el-form-item>
        <el-form-item label="关键词回复">
          <el-switch v-model="settings.form.keyword_reply" />
        </el-form-item>
        <el-form-item label="AI 模式">
          <el-radio-group v-model="settings.form.ai_mode">
            <el-radio-button value="off">关闭</el-radio-button>
            <el-radio-button value="suggest">建议</el-radio-button>
            <el-radio-button value="auto">自动发送</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="人工接管时长（分钟）">
          <el-input-number v-model="settings.form.takeover_minutes" :min="1" :max="1440" />
        </el-form-item>
        <el-form-item label="回复延迟（秒）">
          <div class="range">
            <el-input-number v-model="settings.form.reply_delay_min" :min="0" :step="1" :precision="1" />
            <span>至</span>
            <el-input-number v-model="settings.form.reply_delay_max" :min="0" :step="1" :precision="1" />
          </div>
        </el-form-item>
        <el-form-item label="消息合并窗口（秒）">
          <el-input-number v-model="settings.form.merge_window_seconds" :min="0" :max="30" :precision="1" />
        </el-form-item>
        <el-form-item label="工作时段">
          <el-checkbox v-model="settings.workAllDay">全天</el-checkbox>
          <div v-if="!settings.workAllDay" class="range">
            <el-time-select v-model="settings.workStart" start="00:00" step="00:30" end="23:30" placeholder="开始" />
            <span>至</span>
            <el-time-select v-model="settings.workEnd" start="00:00" step="00:30" end="23:59" placeholder="结束" />
          </div>
        </el-form-item>
        <el-form-item label="默认回复">
          <el-input v-model="settings.form.default_reply" type="textarea" :rows="2" placeholder="留空不发送。例如：在的，稍等马上回复您～" />
        </el-form-item>

        <el-divider content-position="left">发货</el-divider>
        <el-form-item label="自动发货">
          <el-switch v-model="settings.form.auto_delivery" />
          <el-alert v-if="settings.form.auto_delivery && bindingCount === 0" type="warning" :closable="false" show-icon class="mt-s">
            <template #title>还没有任何商品关联了发货内容</template>
            现在打开，买家付款后也不会自动发货。请先到 <router-link to="/orders/cards">自动发货</router-link> 页面新建发货内容并关联商品。
          </el-alert>
        </el-form-item>
        <el-form-item label="发货方式">
          <el-select v-model="settings.form.delivery_mode" class="full">
            <el-option value="send_then_confirm" label="先发消息，再确认发货（推荐）" />
            <el-option value="confirm_then_send" label="先确认发货，再发消息" />
            <el-option value="send_only" label="只发消息，不点发货" />
          </el-select>
        </el-form-item>
        <el-form-item label="自动评价">
          <el-switch v-model="settings.form.auto_rate" />
        </el-form-item>
        <el-form-item v-if="settings.form.auto_rate" label="评价内容">
          <el-input v-model="settings.form.rate_text" />
        </el-form-item>

        <el-divider content-position="left">运营</el-divider>
        <el-form-item label="自动擦亮">
          <el-switch v-model="settings.form.auto_polish" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="drawer-foot">
          <span v-if="automationOn" class="warn small">已开启自动化功能</span>
          <el-button @click="settings.open = false">取消</el-button>
          <el-button type="primary" :loading="settings.saving" @click="saveSettings">保存</el-button>
        </div>
      </template>
    </el-drawer>

    <!-- 风控记录 -->
    <el-dialog v-model="risk.open" :title="`风控记录 · ${risk.account?.nickname || ''}`" width="720px">
      <div class="table-wrap">
        <el-table v-loading="risk.loading" :data="risk.list" size="small" empty-text="暂无风控记录" max-height="420">
          <el-table-column label="时间" width="150">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }"><StatusTag :value="row.state" :map="accountStatusMap" /></template>
          </el-table-column>
          <el-table-column label="原因" prop="reason" min-width="200" show-overflow-tooltip />
          <el-table-column label="验证链接" width="100">
            <template #default="{ row }">
              <el-link v-if="row.punish_url" :href="row.punish_url" target="_blank" type="primary">打开</el-link>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="处理时间" width="150">
            <template #default="{ row }">
              <span v-if="row.resolved_at">{{ fmtTime(row.resolved_at) }}</span>
              <el-tag v-else size="small" type="warning">未处理</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>

    <!-- 账号授权（管理员） -->
    <el-dialog
      v-if="isAdmin"
      v-model="grant.open"
      :title="`账号授权 · ${grant.account?.remark || grant.account?.nickname || grant.account?.unb || ''}`"
      width="560px"
    >
      <el-alert type="info" :closable="false" show-icon title="被授权的用户可以查看和操作该账号的消息、商品和订单。" class="grant-tip" />
      <div class="muted small grant-owner">账号所有者：{{ ownerName }}（管理员可查看全部账号，无需授权）</div>
      <div class="grant-add">
        <el-select v-model="grant.userId" filterable clearable placeholder="选择要授权的用户" class="grant-sel" :loading="grant.loading">
          <el-option v-for="u in grantOptions" :key="u.id" :value="u.id" :label="u.username" :disabled="u.disabled">
            <span>{{ u.username }}</span>
            <span class="muted small opt-hint">{{ u.hint }}</span>
          </el-option>
        </el-select>
        <el-button type="primary" :icon="Plus" :disabled="!grant.userId" :loading="grant.adding" @click="submitGrant">添加授权</el-button>
      </div>
      <div class="table-wrap">
        <el-table v-loading="grant.loading" :data="grant.list" size="small" empty-text="尚未授权给其他用户" max-height="360">
          <el-table-column label="用户" prop="username" min-width="140" />
          <el-table-column label="角色" width="100">
            <template #default="{ row }"><el-tag size="small" type="info">{{ roleMap[row.role] || row.role }}</el-tag></template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button
                size="small"
                link
                type="danger"
                :icon="Delete"
                :loading="busy[`grant-${row.user_id}`]"
                @click="revokeGrant(row as AccountGrant)"
              >移除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.acc {
  display: flex;
  align-items: center;
  gap: 10px;
}
.acc-info {
  min-width: 0;
}
.acc-name {
  font-weight: 600;
}
.acc-remark-row {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
}
.remark-clickable {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  cursor: pointer;
  color: var(--xh-text-muted);
  border-radius: 4px;
  padding: 1px 4px;
  margin-left: -4px;
  transition: all 0.15s ease;
  user-select: none;
}
.remark-clickable:hover {
  color: var(--el-color-primary);
  background-color: var(--el-color-primary-light-9);
}
.remark-text {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.remark-edit-icon {
  font-size: 11px;
  opacity: 0.6;
}
.remark-clickable:hover .remark-edit-icon {
  opacity: 1;
}
.ml {
  margin-left: 4px;
}
.flags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.ops {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ops .el-button + .el-button {
  margin-left: 0;
}
.err {
  color: var(--el-color-danger);
}
.warn {
  color: var(--el-color-warning);
  margin-right: auto;
}
.qr-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}
.full {
  width: 100%;
}
.qr-img {
  width: 232px;
  height: 232px;
  border: 1px solid var(--xh-border);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.qr-img.dim img {
  opacity: 0.2;
}
.qr-status {
  margin-top: 12px;
  font-weight: 600;
}
.qr-status.SUCCESS,
.qr-status.SCANED {
  color: var(--el-color-success);
}
.qr-status.EXPIRED,
.qr-status.ERROR {
  color: var(--el-color-danger);
}
.mt {
  margin-top: 12px;
}
.mt-s {
  margin-top: 8px;
}
.mb {
  margin-bottom: 8px;
}
.range {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.settings-form :deep(.el-form-item__content) {
  flex-direction: column;
  align-items: flex-start;
}
.drawer-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}
.grant-tip {
  margin-bottom: 8px;
}
.grant-owner {
  margin-bottom: 12px;
}
.grant-add {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.grant-sel {
  flex: 1;
  min-width: 0;
}
.opt-hint {
  float: right;
  margin-left: 12px;
}
.session-expired-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 2px 0 4px;
}
.expired-tag {
  font-weight: 500;
}
.relogin-link {
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.relogin-dialog-content {
  padding: 4px 0;
}
.relogin-account-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: var(--xh-bg-elevated);
  border: 1px solid var(--xh-border);
  border-radius: 8px;
  margin-bottom: 16px;
}
.relogin-acc-meta {
  flex: 1;
  min-width: 0;
}
.relogin-acc-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 2px;
}
.relogin-acc-desc {
  line-height: 1.4;
}
.relogin-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}
.relogin-qr-box {
  min-height: 300px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 8px 0;
}
.qr-loading-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 200px;
}
.relogin-qr-actions {
  display: flex;
  gap: 8px;
}
.relogin-proxy-tip {
  color: var(--xh-text-muted);
}
.relogin-form-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
</style>
