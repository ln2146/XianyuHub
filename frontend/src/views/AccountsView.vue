<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Delete,
  Edit,
  Plus,
  Refresh,
  Upload,
  Cellphone,
  Key,
  Check,
  Connection,
  CircleCheckFilled,
  DocumentCopy,
} from '@element-plus/icons-vue'
import QRCode from 'qrcode'
import { errorMessage } from '@/api/http'
import BrowserLoginHelper from '@/components/BrowserLoginHelper.vue'
import { turnOnAutoRenew } from '@/utils/loginHelper'
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
import { accountStatusMap, fmtTime, friendlyError, roleMap } from '@/utils/format'

const store = useAccountsStore()
const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')
const isMobile = useMobile()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const im = ref<ImStatus>({ running: false, accounts: {} })
const busy = reactive<Record<string, boolean>>({})

function checkRouteRelogin() {
  const target = route.query.relogin
  if (!target) return
  const acc = store.list.find((a) => String(a.id) === String(target) || a.unb === String(target))
  if (acc) {
    openReLogin(acc)
    router.replace({ path: '/accounts', query: {} })
  }
}

watch(
  () => route.query.relogin,
  (val) => {
    if (val) checkRouteRelogin()
  },
)

async function load() {
  loading.value = true
  try {
    await store.load(true)
    im.value = await getImStatus().catch(() => ({ running: false, accounts: {} }))
    checkRouteRelogin()
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
  const name = a.remark || a.nickname || a.unb
  const expired = isSessionExpired(a)
  const lines = [
    `删除「${name}」会清除本地的：`,
    '· 会话与聊天记录、商品、订单和发货记录',
    '· 这个账号的自动回复 / 自动发货等设置',
    '· 只作用于这个账号的回复规则和商品发货关联',
    '不可恢复（闲鱼上的真实数据不受影响）。',
    expired
      ? '只是登录失效的话，点「改为重新登录」即可保留全部数据。'
      : '暂时不用的话，可以在「更多」里停用账号，数据都会保留。',
  ]
  try {
    await ElMessageBox.confirm(h('div', { style: 'white-space: pre-line' }, lines.join('\n')), '删除账号', {
      type: 'error',
      confirmButtonText: '确认删除',
      confirmButtonClass: 'el-button--danger',
      cancelButtonText: expired ? '改为重新登录' : '取消',
      distinguishCancelAndClose: true,
    })
  } catch (action) {
    if (action === 'cancel' && expired) openReLogin(a)
    return
  }
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
  qr.id = ''
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
  } catch (err) {
    qr.status = 'ERROR'
    qr.message = errorMessage(err)
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
      ElMessage.success(r.relogin ? '已重新登录，原有设置和数据都已保留' : '扫码登录成功，账号已添加')
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
const cookie = reactive({
  open: false,
  cookies: '',
  proxy: '',
  verify: true,
  saving: false,
  fromBrowser: false,
  autoRenew: true,
})

function openCookie() {
  Object.assign(cookie, { open: true, cookies: '', proxy: '', verify: true, fromBrowser: false })
}

// 用扩展取到的登录态导入成功后，按勾选开启自动续期（失败不影响导入结果）
async function maybeAutoRenew(fromBrowser: boolean, wanted: boolean) {
  if (!fromBrowser || !wanted) return
  try {
    await turnOnAutoRenew()
    ElMessage.success('已开启自动续期：账号掉线时会用这个浏览器的登录态自动恢复')
  } catch (e) {
    ElMessage.warning(`账号已导入，但自动续期没有开启：${(e as Error).message}`)
  }
}

function onBrowserCookies(cookies: string) {
  cookie.cookies = cookies
  cookie.fromBrowser = true
  submitCookie()
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
    await maybeAutoRenew(cookie.fromBrowser, cookie.autoRenew)
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
  fromBrowser: false,
  autoRenew: true,
})
let reloginTimer: number | undefined

function isSessionExpired(row: any): boolean {
  if (!row) return false
  // 只看当前状态：重新登录后 last_error 里可能还留着上次的「Session 过期」
  return row.status === 'need_login'
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
  relogin.fromBrowser = false
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
  } catch (err) {
    relogin.qrStatus = 'ERROR'
    relogin.qrMessage = errorMessage(err)
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
  } catch (err) {
    relogin.qrStatus = 'ERROR'
    relogin.qrMessage = errorMessage(err)
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

function onReLoginBrowserCookies(cookies: string) {
  relogin.cookies = cookies
  relogin.fromBrowser = true
  submitReLoginCookie()
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
    // null = 沿用原代理；空字符串 = 改为直连（null 会被后端当成「沿用」）
    const proxyVal = relogin.useExistingProxy ? null : relogin.proxy.trim()
    const acc = await importCookies({
      cookies: relogin.cookies.trim(),
      proxy: proxyVal,
      verify: relogin.verify,
      account_id: a.id,
    })
    ElMessage.success(`账号「${acc.nickname || acc.unb}」登录态已恢复！`)
    closeReLogin()
    await maybeAutoRenew(relogin.fromBrowser, relogin.autoRenew)
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
              </div>
              <el-tooltip v-if="row.last_error && row.status !== 'active'" :content="row.last_error" placement="top">
                <div class="small err ellipsis">{{ friendlyError(row.last_error) }}</div>
              </el-tooltip>
              <el-link v-if="row.punish_url" :href="row.punish_url" target="_blank" type="danger" class="small">打开验证页面</el-link>
            </template>
          </el-table-column>
          <el-table-column label="操作" :width="isMobile ? 120 : 360" :fixed="isMobile ? undefined : 'right'">
            <template #default="{ row }">
              <div class="ops">
                <el-button v-if="isSessionExpired(row)" size="small" type="danger" @click="openReLogin(row as Account)">
                  重新登录
                </el-button>
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
                      <el-dropdown-item v-if="!isSessionExpired(row)" @click="openReLogin(row as Account)">重新登录</el-dropdown-item>
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
          <el-alert v-if="qr.status === 'ERROR'" :title="qr.message" type="error" :closable="false" class="mb" />
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
      <div v-loading="cookie.saving && cookie.fromBrowser" class="mb">
        <BrowserLoginHelper v-model:auto-renew="cookie.autoRenew" @got="onBrowserCookies" />
      </div>
      <el-form label-position="top">
        <el-form-item label="或者手动粘贴 Cookie">
          <el-input
            v-model="cookie.cookies"
            type="textarea"
            :rows="5"
            placeholder="粘贴 goofish.com Cookie 字符串或 JSON（需含 unb、cookie2、_m_h5_tk）"
            @input="cookie.fromBrowser = false"
          />
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
      class="relogin-modern-dialog"
      width="540px"
      destroy-on-close
      @closed="closeReLogin"
    >
      <template #header>
        <div class="relogin-dialog-header">
          <div class="relogin-header-icon">
            <el-icon><Refresh /></el-icon>
          </div>
          <div class="relogin-header-title-wrap">
            <div class="relogin-header-title">重新授权登录</div>
            <div class="relogin-header-subtitle">为已失效账号刷新凭证，恢复自动化同步与消息收发</div>
          </div>
        </div>
      </template>

      <div class="relogin-dialog-content">
        <!-- 账号身份卡片 -->
        <div class="relogin-account-card">
          <div class="acc-avatar-wrap">
            <el-avatar
              v-if="relogin.account?.avatar"
              :size="46"
              :src="relogin.account.avatar"
              class="acc-avatar-img"
            />
            <div v-else class="acc-avatar-gradient">
              <span>{{ (relogin.account?.nickname || relogin.account?.unb || '闲').slice(0, 1) }}</span>
            </div>
          </div>
          <div class="acc-info-col">
            <div class="acc-title-row">
              <span class="acc-name">{{ relogin.account?.nickname || relogin.account?.unb }}</span>
              <span class="acc-status-badge expired">
                <span class="dot"></span>
                <span>登录已失效</span>
              </span>
            </div>
            <div class="acc-tags-row">
              <span class="acc-id-chip">
                <span class="chip-label">ID</span>
                <span class="chip-val">{{ relogin.account?.unb }}</span>
              </span>
              <span v-if="relogin.account?.has_proxy" class="acc-proxy-chip">
                <el-icon><Connection /></el-icon>
                <span>已配专属代理</span>
              </span>
            </div>
          </div>
        </div>

        <div class="relogin-reassurance-note">
          <el-icon class="note-icon"><CircleCheckFilled /></el-icon>
          <span>重新授权成功后将自动恢复商品关联与自动回复，无需重新创建</span>
        </div>

        <!-- 选项卡切换 (Segmented Control) -->
        <div class="relogin-segmented-nav">
          <button
            type="button"
            class="seg-nav-item"
            :class="{ active: relogin.tab === 'qr' }"
            @click="relogin.tab = 'qr'"
          >
            <el-icon><Cellphone /></el-icon>
            <span>闲鱼 App 扫码</span>
            <span class="seg-badge-rec">极速推荐</span>
          </button>
          <button
            type="button"
            class="seg-nav-item"
            :class="{ active: relogin.tab === 'cookie' }"
            @click="relogin.tab = 'cookie'"
          >
            <el-icon><Key /></el-icon>
            <span>导入新 Cookie</span>
          </button>
        </div>

        <!-- Tab 1: 闲鱼 App 扫码 -->
        <div v-if="relogin.tab === 'qr'" class="relogin-tab-content">
          <div class="relogin-qr-container">
            <template v-if="relogin.qrStarting && !relogin.qrImage">
              <div class="qr-loading-box">
                <el-icon class="is-loading" :size="36"><Refresh /></el-icon>
                <div class="loading-text">正在生成闲鱼安全登录二维码...</div>
              </div>
            </template>
            <template v-else>
              <div class="qr-frame-box">
                <div class="qr-img-wrapper" :class="{ dim: ['EXPIRED', 'CANCELED', 'ERROR'].includes(relogin.qrStatus) }">
                  <img v-if="relogin.qrImage" :src="relogin.qrImage" alt="登录二维码" class="qr-core-img" />
                </div>
                <div v-if="['EXPIRED', 'CANCELED', 'ERROR'].includes(relogin.qrStatus)" class="qr-expired-overlay">
                  <div class="overlay-text">{{ relogin.qrStatus === 'EXPIRED' ? '二维码已失效' : '扫码未完成' }}</div>
                  <el-button type="primary" size="small" :loading="relogin.qrStarting" @click="startReLoginQr">
                    点击刷新
                  </el-button>
                </div>
              </div>

              <div class="qr-status-pill" :class="relogin.qrStatus">
                <span class="status-pulse-dot"></span>
                <span>{{ qrStatusText[relogin.qrStatus] || relogin.qrStatus }}</span>
              </div>

              <div v-if="relogin.qrMessage && relogin.qrStatus !== 'NEW'" class="qr-sub-message">
                {{ relogin.qrMessage }}
              </div>

              <el-alert v-if="relogin.qrStatus === 'NEED_VERIFY'" type="warning" :closable="false" class="qr-verify-alert">
                <div class="verify-alert-content">
                  <div>闲鱼要求身份验证（人脸 / 短信），请在浏览器中打开链接完成验证：</div>
                  <div class="verify-action-row">
                    <el-link v-if="relogin.qrVerifyUrl" :href="relogin.qrVerifyUrl" target="_blank" type="primary">
                      打开验证页面 ↗
                    </el-link>
                    <el-button size="small" type="primary" @click="pollReLoginQr">已完成，继续检测</el-button>
                  </div>
                </div>
              </el-alert>

              <div v-if="!['EXPIRED', 'CANCELED', 'ERROR'].includes(relogin.qrStatus)" class="relogin-qr-actions">
                <el-button
                  size="default"
                  :loading="relogin.qrStarting"
                  @click="startReLoginQr"
                >
                  <el-icon><Refresh /></el-icon>
                  <span>重新生成二维码</span>
                </el-button>
              </div>

              <div v-if="relogin.account?.has_proxy" class="relogin-proxy-tip">
                <el-icon><Connection /></el-icon>
                <span>已自动使用此账号绑定的专属代理通道进行扫码握手</span>
              </div>
            </template>
          </div>
        </div>

        <!-- Tab 2: 导入新 Cookie -->
        <div v-else class="relogin-tab-content">
          <div v-loading="relogin.submitting && relogin.fromBrowser" class="helper-box-wrap">
            <BrowserLoginHelper
              v-model:auto-renew="relogin.autoRenew"
              :expect-unb="relogin.account?.unb"
              @got="onReLoginBrowserCookies"
            />
          </div>

          <div class="manual-cookie-section">
            <div class="section-divider-row">
              <span class="divider-line"></span>
              <span class="divider-title">
                <el-icon><DocumentCopy /></el-icon>
                <span>或者手动粘贴最新 Cookie</span>
              </span>
              <span class="divider-line"></span>
            </div>

            <div class="textarea-wrapper">
              <el-input
                v-model="relogin.cookies"
                type="textarea"
                :rows="3"
                @input="relogin.fromBrowser = false"
                placeholder="粘贴 goofish.com 最新的 Cookie 字符串或导出的 JSON（需含 unb、cookie2、_m_h5_tk）"
                class="custom-cookie-textarea"
              />
            </div>

            <!-- 代理设置 -->
            <div v-if="relogin.account?.has_proxy" class="proxy-config-card">
              <div class="proxy-config-header" @click="relogin.useExistingProxy = !relogin.useExistingProxy">
                <div class="proxy-config-left">
                  <el-icon class="proxy-icon"><Connection /></el-icon>
                  <div class="proxy-config-text">
                    <span class="proxy-title">沿用该账号原专属代理</span>
                    <span class="proxy-desc">保持原网络环境，避免频繁触发异地安全校验</span>
                  </div>
                </div>
                <el-switch
                  v-model="relogin.useExistingProxy"
                  inline-prompt
                  active-text="是"
                  inactive-text="否"
                  @click.stop
                />
              </div>
              <transition name="el-zoom-in-top">
                <div v-if="!relogin.useExistingProxy" class="proxy-input-wrap">
                  <el-input
                    v-model="relogin.proxy"
                    placeholder="留空表示直连，或填写 http://user:pass@host:port"
                    clearable
                  >
                    <template #prefix><el-icon><Connection /></el-icon></template>
                  </el-input>
                </div>
              </transition>
            </div>

            <div v-else class="proxy-optional-row">
              <div class="proxy-opt-label">网络代理（可选）</div>
              <el-input
                v-model="relogin.proxy"
                placeholder="http://user:pass@host:port 或 socks5://…"
                clearable
              >
                <template #prefix><el-icon><Connection /></el-icon></template>
              </el-input>
            </div>

            <!-- 校验开关 -->
            <div class="verify-row">
              <el-checkbox v-model="relogin.verify">
                <span class="verify-label">更新前校验登录状态有效性</span>
              </el-checkbox>
              <span class="verify-rec-tag">推荐开启</span>
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="relogin-footer-actions">
          <el-button class="footer-btn-cancel" @click="closeReLogin">取消</el-button>
          <el-button
            v-if="relogin.tab === 'cookie'"
            type="primary"
            class="footer-btn-submit"
            :loading="relogin.submitting"
            @click="submitReLoginCookie"
          >
            <el-icon v-if="!relogin.submitting"><Check /></el-icon>
            <span>更新并恢复登录</span>
          </el-button>
          <el-button
            v-else-if="['EXPIRED', 'CANCELED', 'ERROR'].includes(relogin.qrStatus)"
            type="primary"
            class="footer-btn-submit"
            :loading="relogin.qrStarting"
            @click="startReLoginQr"
          >
            <el-icon v-if="!relogin.qrStarting"><Refresh /></el-icon>
            <span>刷新二维码</span>
          </el-button>
        </div>
      </template>
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
          <div class="form-tip">关闭时不会替你发出任何消息；关闭期间收到的消息，重新打开后也不会补回复。</div>
        </el-form-item>
        <el-form-item label="关键词回复">
          <el-switch v-model="settings.form.keyword_reply" />
          <div class="form-tip">优先于 AI：命中「回复规则」时直接发规则里的话术，不受工作时段限制。</div>
        </el-form-item>
        <el-form-item label="AI 模式">
          <el-radio-group v-model="settings.form.ai_mode">
            <el-radio-button value="off">关闭</el-radio-button>
            <el-radio-button value="suggest">建议</el-radio-button>
            <el-radio-button value="auto">自动发送</el-radio-button>
          </el-radio-group>
          <div class="form-tip">
            {{
              settings.form.ai_mode === 'auto'
                ? settings.form.auto_reply
                  ? 'AI 写好就直接发给买家。'
                  : '总开关关闭时 AI 不工作；想先看看 AI 怎么回，可以改用「建议」。'
                : settings.form.ai_mode === 'suggest'
                  ? 'AI 只在收件箱里给出建议，由你确认后发送；即使总开关关闭也会生成建议（消耗模型额度）。'
                  : '不调用 AI，只用关键词回复和默认回复。'
            }}
          </div>
        </el-form-item>
        <el-form-item label="人工接管时长（分钟）">
          <el-input-number v-model="settings.form.takeover_minutes" :min="1" :max="1440" />
          <div class="form-tip">你亲自回复后，这个会话暂停自动回复的时长；期间买家再发消息会提醒你。</div>
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
          <div class="form-tip">只限制 AI 回复；关键词回复和默认回复在工作时段外照常发送。</div>
        </el-form-item>
        <el-form-item label="默认回复">
          <el-input v-model="settings.form.default_reply" type="textarea" :rows="2" placeholder="留空不发送。例如：在的，稍等马上回复您～" />
          <div class="form-tip">AI 关闭或在工作时段外时使用，每个会话只发一次。</div>
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
/* 重新登录弹窗现代化样式 */
:deep(.relogin-modern-dialog) {
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 20px 40px -12px rgba(15, 23, 42, 0.15), 0 0 0 1px rgba(15, 23, 42, 0.05);
}

:deep(.relogin-modern-dialog .el-dialog__header) {
  margin-right: 0;
  padding: 18px 24px 14px;
  border-bottom: 1px solid var(--xh-border, #e2e8f0);
}

:deep(.relogin-modern-dialog .el-dialog__body) {
  padding: 20px 24px 16px;
}

:deep(.relogin-modern-dialog .el-dialog__footer) {
  padding: 14px 24px 18px;
  border-top: 1px solid var(--xh-border, #e2e8f0);
  background: var(--xh-fill, #f8fafc);
}

.relogin-dialog-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.relogin-header-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(30, 158, 106, 0.12) 0%, rgba(16, 185, 129, 0.06) 100%);
  color: var(--xh-primary, #1e9e6a);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.relogin-header-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.relogin-header-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--xh-text, #0f172a);
  line-height: 1.3;
}

.relogin-header-subtitle {
  font-size: 12px;
  color: var(--xh-muted, #64748b);
  line-height: 1.4;
}

.relogin-dialog-content {
  padding: 0;
}

/* 账号卡片 */
.relogin-account-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 16px;
  background: linear-gradient(135deg, rgba(248, 250, 252, 0.95) 0%, rgba(241, 245, 249, 0.7) 100%);
  border: 1px solid var(--xh-border, #e2e8f0);
  border-radius: 12px;
}

.acc-avatar-wrap {
  flex-shrink: 0;
}

.acc-avatar-gradient {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: linear-gradient(135deg, #f59e0b 0%, #ea580c 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  font-size: 17px;
  font-weight: 700;
  box-shadow: 0 3px 10px rgba(245, 158, 11, 0.25);
}

.acc-avatar-img {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.acc-info-col {
  flex: 1;
  min-width: 0;
}

.acc-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 5px;
}

.acc-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--xh-text, #0f172a);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.acc-status-badge.expired {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 600;
  color: #dc2626;
  background: #fef2f2;
  border: 1px solid #fecaca;
  padding: 2px 8px;
  border-radius: 99px;
  flex-shrink: 0;
}

.acc-status-badge .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #ef4444;
  box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.2);
  animation: pulseDot 2s infinite;
}

.acc-tags-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.acc-id-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  background: #ffffff;
  border: 1px solid var(--xh-border, #e2e8f0);
  border-radius: 6px;
  padding: 1px 7px;
  color: #475569;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.acc-id-chip .chip-label {
  color: #94a3b8;
  font-weight: 600;
  font-size: 10px;
}

.acc-proxy-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  border-radius: 6px;
  padding: 1px 7px;
  color: #059669;
  font-weight: 500;
}

.relogin-reassurance-note {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--xh-muted, #64748b);
  margin-top: 10px;
  padding: 0 4px;
}

.relogin-reassurance-note .note-icon {
  color: #10b981;
  font-size: 14px;
  flex-shrink: 0;
}

/* 分段选项卡切换 */
.relogin-segmented-nav {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  background: var(--xh-fill-strong, #f1f5f9);
  padding: 4px;
  border-radius: 12px;
  margin: 16px 0 14px;
}

.seg-nav-item {
  border: none;
  background: transparent;
  height: 38px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--xh-text-2, #64748b);
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.seg-nav-item:hover {
  color: var(--xh-text, #0f172a);
}

.seg-nav-item.active {
  background: #ffffff;
  color: var(--xh-text, #0f172a);
  font-weight: 600;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06), 0 1px 2px rgba(0, 0, 0, 0.04);
}

.seg-badge-rec {
  background: #dcfce7;
  color: #166534;
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 99px;
}

/* Tab 1 扫码内容 */
.relogin-qr-container {
  min-height: 280px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 10px 0 4px;
}

.qr-frame-box {
  position: relative;
  padding: 10px;
  background: #ffffff;
  border: 1px solid var(--xh-border, #e2e8f0);
  border-radius: 14px;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.05);
  margin-bottom: 14px;
}

.qr-img-wrapper {
  transition: filter 0.2s ease;
}

.qr-img-wrapper.dim {
  filter: blur(2px) grayscale(60%);
  opacity: 0.5;
}

.qr-core-img {
  width: 190px;
  height: 190px;
  display: block;
  border-radius: 8px;
}

.qr-expired-overlay {
  position: absolute;
  inset: 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(4px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
}

.qr-expired-overlay .overlay-text {
  font-size: 13px;
  font-weight: 600;
  color: #ef4444;
}

.qr-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 14px;
  border-radius: 99px;
  font-size: 13px;
  font-weight: 500;
  background: var(--xh-fill, #f1f5f9);
  color: var(--xh-text, #1e293b);
  border: 1px solid var(--xh-border, #e2e8f0);
}

.qr-status-pill .status-pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2);
  animation: pulseDot 2s infinite;
}

.qr-status-pill.EXPIRED .status-pulse-dot,
.qr-status-pill.CANCELED .status-pulse-dot,
.qr-status-pill.ERROR .status-pulse-dot {
  background: #ef4444;
  box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.2);
  animation: none;
}

.qr-status-pill.NEED_VERIFY .status-pulse-dot {
  background: #f59e0b;
  box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.2);
}

.qr-sub-message {
  font-size: 12px;
  color: var(--xh-muted, #64748b);
  margin-top: 6px;
}

.qr-verify-alert {
  margin-top: 12px;
  width: 100%;
}

.verify-alert-content {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
}

.verify-action-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
}

.relogin-qr-actions {
  display: flex;
  gap: 8px;
  margin-top: 14px;
}

.relogin-proxy-tip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--xh-muted, #64748b);
  margin-top: 10px;
}

/* Tab 2 Cookie 内容 */
.manual-cookie-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-divider-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 14px 0 2px;
}

.divider-line {
  flex: 1;
  height: 1px;
  background: var(--xh-border, #e2e8f0);
}

.divider-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--xh-muted, #64748b);
  display: flex;
  align-items: center;
  gap: 6px;
}

.custom-cookie-textarea :deep(.el-textarea__inner) {
  border-radius: 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  background: var(--xh-fill, #f8fafc);
  border-color: var(--xh-border, #e2e8f0);
  transition: all 0.2s ease;
}

.custom-cookie-textarea :deep(.el-textarea__inner:focus) {
  background: #ffffff;
  border-color: var(--xh-primary, #1e9e6a);
  box-shadow: 0 0 0 3px rgba(30, 158, 106, 0.12);
}

.proxy-config-card {
  background: var(--xh-fill, #f8fafc);
  border: 1px solid var(--xh-border, #e2e8f0);
  border-radius: 10px;
  padding: 12px 14px;
}

.proxy-config-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
}

.proxy-config-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.proxy-icon {
  font-size: 18px;
  color: var(--xh-primary, #1e9e6a);
}

.proxy-config-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.proxy-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--xh-text, #1e293b);
}

.proxy-desc {
  font-size: 11px;
  color: var(--xh-muted, #64748b);
}

.proxy-input-wrap {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--xh-border, #e2e8f0);
}

.proxy-optional-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.proxy-opt-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--xh-text-2, #475569);
}

.verify-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 2px;
}

.verify-label {
  font-size: 13px;
  color: var(--xh-text, #334155);
}

.verify-rec-tag {
  font-size: 11px;
  color: var(--xh-primary, #1e9e6a);
  font-weight: 500;
  background: var(--xh-primary-soft, #e8f5f0);
  padding: 1px 8px;
  border-radius: 99px;
}

/* 底部操作按钮 */
.relogin-footer-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  width: 100%;
}

.footer-btn-cancel {
  border-radius: 8px;
  padding: 8px 18px;
}

.footer-btn-submit {
  border-radius: 8px;
  padding: 8px 20px;
  font-weight: 500;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important;
  border: none !important;
  box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3);
  transition: all 0.2s ease;
}

.footer-btn-submit:hover {
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4);
  transform: translateY(-1px);
}

@keyframes pulseDot {
  0% {
    transform: scale(0.95);
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.5);
  }
  70% {
    transform: scale(1);
    box-shadow: 0 0 0 5px rgba(16, 185, 129, 0);
  }
  100% {
    transform: scale(0.95);
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
  }
}
</style>
