<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type UploadRequestOptions } from 'element-plus'
import {
  ArrowRight,
  Check,
  Coin,
  Delete,
  Document,
  Goods,
  Lock,
  MagicStick,
  Plus,
  Refresh,
  Search,
  Tickets,
  Upload,
  User,
  WarningFilled,
} from '@element-plus/icons-vue'
import {
  createRule,
  deleteKnowledgeDoc,
  deleteRule,
  listKnowledgeDocs,
  listRules,
  updateKnowledgeDoc,
  updateRule,
  uploadKnowledgeDoc,
  type KnowledgeDoc,
  type RuleIn,
  type RuleOut,
} from '@/api/message'
import { updateAccount, type Account } from '@/api/account'
import { listItems, updateItem, type MyItem } from '@/api/goods'
import { useAccountsStore } from '@/stores/accounts'
import { useMobile } from '@/composables/useMobile'
import StatusTag from '@/components/StatusTag.vue'
import ImageUploader from '@/components/ImageUploader.vue'
import { accountStatusMap, fmtMoney, goodsStatusMap } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const accounts = useAccountsStore()
const isMobile = useMobile()

// ---------------------------------------------------------------- Tab 状态
const activeTab = ref<'rules' | 'ai' | 'guard'>('rules')
if (route.query.tab && ['rules', 'ai', 'guard'].includes(String(route.query.tab))) {
  activeTab.value = route.query.tab as 'rules' | 'ai' | 'guard'
}

watch(
  () => route.query.tab,
  (t) => {
    if (t && ['rules', 'ai', 'guard'].includes(String(t))) {
      activeTab.value = t as 'rules' | 'ai' | 'guard'
    }
  },
)

function onTabChange(name: string | number) {
  router.replace({ query: { ...route.query, tab: String(name) } }).catch(() => undefined)
}

// ---------------------------------------------------------------- 账号列表与就地控制
const busyAccount = reactive<Record<string, boolean>>({})
const enablingPreset = reactive<Record<string, boolean>>({})

const selectedAccountId = ref<number | undefined>(undefined)
const currentAccount = computed<Account | undefined>(() =>
  accounts.list.find((a) => a.id === selectedAccountId.value) || accounts.list[0],
)

watch(
  () => accounts.list,
  (list) => {
    if ((selectedAccountId.value === undefined || !list.some((a) => a.id === selectedAccountId.value)) && list.length > 0) {
      selectedAccountId.value = list[0].id
    }
  },
  { immediate: true },
)

async function toggleAccountAutoReply(a: Account, val: boolean) {
  busyAccount[`ar-${a.id}`] = true
  try {
    await updateAccount(a.id, { settings: { auto_reply: val } })
    a.settings.auto_reply = val
    ElMessage.success(`账号「${a.remark || a.nickname}」已${val ? '开启' : '关闭'}自动回复`)
  } catch {
    /* 拦截器已处理 */
  } finally {
    busyAccount[`ar-${a.id}`] = false
  }
}

const aiModeOptions = [
  { label: '关闭', value: 'off' },
  { label: '建议模式', value: 'suggest' },
  { label: '全自动回复', value: 'auto' },
]

async function setAiMode(a: Account, mode: 'off' | 'suggest' | 'auto') {
  busyAccount[`ai-${a.id}`] = true
  try {
    const settings = mode === 'auto' ? { ai_mode: mode, auto_reply: true } : { ai_mode: mode }
    await updateAccount(a.id, { settings })
    Object.assign(a.settings, settings)
    ElMessage.success(
      mode === 'off'
        ? 'AI 回复已关闭，只按关键词规则回复'
        : mode === 'suggest'
          ? 'AI 建议模式已开启：将在收件箱给出回复建议，由你确认发送'
          : 'AI 全自动回复已开启：关键词未命中时自动应答',
    )
  } catch {
    /* 拦截器已处理 */
  } finally {
    busyAccount[`ai-${a.id}`] = false
  }
}

async function toggleAccountKeywordReply(a: Account, val: boolean) {
  busyAccount[`kw-${a.id}`] = true
  try {
    await updateAccount(a.id, { settings: { keyword_reply: val } })
    a.settings.keyword_reply = val
    ElMessage.success(`账号「${a.remark || a.nickname}」已${val ? '开启' : '关闭'}关键词回复`)
  } catch {
    /* 拦截器已处理 */
  } finally {
    busyAccount[`kw-${a.id}`] = false
  }
}

// ---------------------------------------------------------------- Tab 1: 关键词规则
const rules = ref<RuleOut[]>([])
const loading = ref(false)
const ruleSearch = ref('')
const ruleAccountFilter = ref<number | undefined>(undefined)

const matchLabel: Record<string, string> = { contains: '包含', exact: '完全匹配', regex: '正则' }

async function loadRules() {
  loading.value = true
  try {
    rules.value = await listRules()
  } finally {
    loading.value = false
  }
}

const filteredRules = computed(() => {
  const kw = ruleSearch.value.trim().toLowerCase()
  return rules.value.filter((r) => {
    if (ruleAccountFilter.value !== undefined && r.account_id !== null && r.account_id !== ruleAccountFilter.value) {
      return false
    }
    if (!kw) return true
    const matchName = (r.name || '').toLowerCase().includes(kw)
    const matchKws = r.keywords.some((k) => k.toLowerCase().includes(kw))
    const matchReply = r.reply.toLowerCase().includes(kw)
    return matchName || matchKws || matchReply
  })
})

const empty = (): RuleIn => ({
  name: '',
  account_id: null,
  item_id: null,
  keywords: [],
  match: 'contains',
  action: 'reply',
  reply: '',
  images: [],
  priority: 0,
  reply_once: false,
  enabled: true,
})

const edit = reactive({ open: false, saving: false, id: null as number | null, form: empty() })
const imgUploading = ref(0)

function openCreate() {
  Object.assign(edit, { open: true, id: null, form: empty() })
}

function openEdit(r: RuleOut) {
  const { id: _id, hits: _hits, ...rest } = r
  Object.assign(edit, {
    open: true,
    id: r.id,
    form: { ...rest, keywords: [...r.keywords], images: [...(r.images || [])] },
  })
}

function toIn(r: RuleOut): RuleIn {
  const { id: _id, hits: _hits, ...rest } = r
  return rest
}

const PLACEHOLDER = /【[^】]*】/

async function saveRule() {
  const f = edit.form
  if (!f.keywords.length) return ElMessage.warning('至少需要一个关键词')
  if (f.action === 'reply' && !f.reply.trim() && !f.images.length) return ElMessage.warning('请填写回复内容或添加图片')
  if (imgUploading.value) return ElMessage.warning('图片还在上传，请稍等')
  if (PLACEHOLDER.test(f.reply)) return ElMessage.warning('请先把【】里的内容改成你的实际情况，再保存')
  if (f.match === 'regex') {
    for (const k of f.keywords) {
      try {
        new RegExp(k)
      } catch {
        return ElMessage.warning(`正则表达式无效：${k}`)
      }
    }
  }
  edit.saving = true
  try {
    // 转人工规则不发图片
    const body: RuleIn = { ...f, item_id: f.item_id?.trim() || null, images: f.action === 'reply' ? f.images : [] }
    if (edit.id) await updateRule(edit.id, body)
    else await createRule(body)
    ElMessage.success('已保存规则')
    edit.open = false
    await loadRules()
  } catch {
    /* 拦截器已提示 */
  } finally {
    edit.saving = false
  }
}

async function toggle(r: RuleOut, enabled: boolean) {
  try {
    await updateRule(r.id, { ...toIn(r), enabled })
    r.enabled = enabled
    ElMessage.success(enabled ? '已启用规则' : '已停用规则')
  } catch {
    /* 拦截器已提示 */
  }
}

async function remove(r: RuleOut) {
  await ElMessageBox.confirm(`删除规则「${r.name || r.keywords.join('、')}」？`, '删除规则', { type: 'warning' })
  await deleteRule(r.id)
  ElMessage.success('已删除')
  await loadRules()
}

// 常用模板
interface PresetTemplate {
  name: string
  keywords: string[]
  reply: string
  safe: boolean
  note?: string
}

const presetTemplates: PresetTemplate[] = [
  {
    name: '在线问候',
    keywords: ['在吗', '还在吗', '在不在', '有人吗'],
    reply: '在的～商品还在，有什么想了解的可以直接问我。',
    safe: true,
  },
  {
    name: '议价应答',
    keywords: ['少点', '便宜点', '最低多少', '能少吗', '大刀'],
    reply: '价格已经比较实在啦，诚心要的话可以直接拍下，我看到会尽快处理～',
    safe: true,
    note: '若已在「商品管理」设置底价和议价阶梯，关键词回复会优先拦截，如需让 AI 自动议价可暂不开启此规则。',
  },
  {
    name: '发货与快递',
    keywords: ['发什么快递', '什么时候发货', '今天能发吗', '发货时效'],
    reply: '拍下后【24 小时内】发出，默认【中通】，需要其他快递可以留言。',
    safe: false,
  },
  {
    name: '包邮与运费',
    keywords: ['包邮吗', '包不包邮', '运费多少'],
    reply: '【默认包邮，偏远地区除外】。',
    safe: false,
  },
  {
    name: '成色与验货',
    keywords: ['是正品吗', '正品不', '保真吗', '支持验货吗'],
    reply: '宝贝是【自用】的，实物拍摄，成色以图片和描述为准；【支持验货宝】。',
    safe: false,
  },
]

function applyPreset(tpl: PresetTemplate) {
  Object.assign(edit, {
    open: true,
    id: null,
    form: {
      ...empty(),
      name: tpl.name,
      keywords: [...tpl.keywords],
      reply: tpl.reply,
    },
  })
}

async function quickEnableTemplate(tpl: PresetTemplate) {
  if (!tpl.safe) return applyPreset(tpl)
  enablingPreset[tpl.name] = true
  try {
    await createRule({
      name: tpl.name,
      account_id: null,
      item_id: null,
      keywords: [...tpl.keywords],
      match: 'contains',
      action: 'reply',
      reply: tpl.reply,
      images: [],
      priority: 0,
      reply_once: false,
      enabled: true,
    })
    ElMessage.success(`已启用模板「${tpl.name}」`)
    await loadRules()
  } catch {
    /* 拦截器提示 */
  } finally {
    enablingPreset[tpl.name] = false
  }
}

// ---------------------------------------------------------------- Tab 2: AI 设定与知识库
const MAX_INSTRUCTIONS = 2000
const instructions = ref('')
const savingInstr = ref(false)

watch(
  currentAccount,
  (a) => {
    instructions.value = a?.settings.ai_instructions || ''
  },
  { immediate: true },
)

const instrDirty = computed(() => instructions.value !== (currentAccount.value?.settings.ai_instructions || ''))

const promptChips = [
  { label: '统一发中通', text: '统一发中通快递，偏远地区（新疆/西藏等）不包邮' },
  { label: '17点前当天发', text: '每天下午 17:00 前拍下当天发出，节假日除外' },
  { label: '谢绝大刀', text: '商品均实拍底价，不接大刀，诚心要可小幅优惠' },
  { label: '亲切叫“宝”', text: '说话亲切自然，可以适当称呼“宝”或“朋友”，不机械生硬' },
  { label: '支持验货宝', text: '支持验货宝，所见即所得，非假货不退不换' },
  { label: '自用转让', text: '个人自用闲置转让，非职业卖家，成色如实实拍' },
  { label: '拍下自动发货', text: '电子卡券/资料拍下后系统自动发货，发出后不支持退换' },
  { label: '二手不退换', text: '二手闲置物品不支持无理由退换货，拍前请确认好成色' },
]

function appendPromptChip(chip: { label: string; text: string }) {
  const current = instructions.value.trim()
  if (current.includes(chip.text)) {
    ElMessage.info(`人设中已包含「${chip.label}」`)
    return
  }
  if (!current) {
    instructions.value = `· ${chip.text}`
  } else {
    instructions.value = `${current}\n· ${chip.text}`
  }
}

async function saveInstructions() {
  if (!currentAccount.value) return
  savingInstr.value = true
  try {
    await updateAccount(currentAccount.value.id, { settings: { ai_instructions: instructions.value.trim() } })
    await accounts.load(true)
    ElMessage.success('已保存店铺人设说明，AI 回复将立即生效')
  } finally {
    savingInstr.value = false
  }
}

// 默认议价与 AI 禁用词
const guard = reactive({
  bargain_default: false,
  bargain_max_percent: 10,
  bargain_max_amount: null as number | null,
  bargain_max_rounds: 3,
  ai_banned_words: [] as string[],
})
const savingGuard = ref(false)

function guardFrom(a?: Account) {
  const st = a?.settings
  return {
    bargain_default: st?.bargain_default ?? false,
    bargain_max_percent: st?.bargain_max_percent ?? 10,
    bargain_max_amount: st?.bargain_max_amount ?? null,
    bargain_max_rounds: st?.bargain_max_rounds ?? 3,
    ai_banned_words: [...(st?.ai_banned_words ?? [])],
  }
}

watch(currentAccount, (a) => Object.assign(guard, guardFrom(a)), { immediate: true })

const guardDirty = computed(() => JSON.stringify(guardFrom(currentAccount.value)) !== JSON.stringify(guard))

async function saveGuard() {
  if (!currentAccount.value) return
  savingGuard.value = true
  try {
    await updateAccount(currentAccount.value.id, {
      settings: { ...guard, ai_banned_words: guard.ai_banned_words.map((w) => w.trim()).filter(Boolean) },
    })
    await accounts.load(true)
    ElMessage.success('已保存议价范围与禁用词')
  } finally {
    savingGuard.value = false
  }
}

// 资料文件
const docs = ref<KnowledgeDoc[]>([])
const docsLoading = ref(false)
const uploadScope = ref<'all' | 'account'>('account')
const ACCEPT = '.txt,.md,.csv,.pdf,.docx'

async function loadDocs() {
  docsLoading.value = true
  try {
    docs.value = await listKnowledgeDocs()
  } finally {
    docsLoading.value = false
  }
}

// 店铺资料：所有账号通用 + 当前账号（不含某件商品专属的资料）
const shopDocs = computed(() =>
  docs.value.filter((d) => !d.item_id && (d.account_id === null || d.account_id === currentAccount.value?.id)),
)

async function uploadShop(opts: UploadRequestOptions) {
  const accountId = uploadScope.value === 'account' ? (currentAccount.value?.id ?? null) : null
  const d = await uploadKnowledgeDoc(opts.file, accountId)
  docs.value.unshift(d)
  ElMessage.success(`已解析「${d.name}」，共 ${d.chars.toLocaleString()} 字`)
}

// ---------------------------------------------------------------- 商品知识库（当前账号的商品）
const accountItems = ref<MyItem[]>([])
const itemsLoading = ref(false)
const itemQuery = ref('')

async function loadItems() {
  const id = currentAccount.value?.id
  if (!id) return
  itemsLoading.value = true
  try {
    const list = await listItems({ account_id: id })
    if (currentAccount.value?.id === id) accountItems.value = list
  } catch {
    /* 拦截器已提示 */
  } finally {
    itemsLoading.value = false
  }
}
watch(() => currentAccount.value?.id, loadItems, { immediate: true })

// 在售的排前面，其次已补充过的
const filteredItems = computed(() => {
  const q = itemQuery.value.trim().toLowerCase()
  return accountItems.value
    .filter((it) => !q || it.title.toLowerCase().includes(q))
    .sort((a, b) => Number(b.status === 'on_sale') - Number(a.status === 'on_sale'))
})

function docsOfItem(it: MyItem) {
  return docs.value.filter((d) => d.item_id === it.item_id && d.account_id === it.account_id)
}
const itemDocCount = (it: MyItem) => docsOfItem(it).length

const kb = reactive({ open: false, item: null as MyItem | null, text: '', saving: false })
const kbDocs = computed(() => (kb.item ? docsOfItem(kb.item) : []))
const kbDirty = computed(() => !!kb.item && kb.text !== (kb.item.knowledge || ''))

function openKb(it: MyItem) {
  Object.assign(kb, { open: true, item: it, text: it.knowledge || '' })
}

async function saveKb() {
  const it = kb.item
  if (!it) return
  kb.saving = true
  try {
    const updated = await updateItem(it.id, { knowledge: kb.text.trim() })
    Object.assign(it, updated)
    kb.text = it.knowledge || ''
    ElMessage.success('已保存，AI 回答这件商品的咨询时会参考')
  } finally {
    kb.saving = false
  }
}

async function uploadItemDoc(opts: UploadRequestOptions) {
  const it = kb.item
  if (!it) return
  const d = await uploadKnowledgeDoc(opts.file, it.account_id, it.item_id)
  docs.value.unshift(d)
  ElMessage.success(`已解析「${d.name}」，共 ${d.chars.toLocaleString()} 字`)
}

async function toggleDoc(d: KnowledgeDoc, enabled: boolean) {
  const updated = await updateKnowledgeDoc(d.id, { enabled })
  Object.assign(d, updated)
}

async function removeDoc(d: KnowledgeDoc) {
  await ElMessageBox.confirm(`删除知识库资料「${d.name}」？删除后 AI 将不再参考该文档。`, '删除资料', {
    type: 'warning',
  })
  await deleteKnowledgeDoc(d.id)
  docs.value = docs.value.filter((x) => x.id !== d.id)
  ElMessage.success('已删除知识库资料')
}

// ---------------------------------------------------------------- 综合刷新
async function refreshAll() {
  await Promise.all([loadRules(), loadDocs(), loadItems(), accounts.load().catch(() => undefined)])
  ElMessage.success('已刷新最新配置')
}

onMounted(() => {
  loadRules()
  loadDocs()
  accounts.load().catch(() => undefined)
})
</script>

<template>
  <div class="page rules-page">
    <!-- 顶部统一控制台横幅：页面标题 + 账号选择 + 总开关 + 刷新 -->
    <div class="studio-header-card">
      <div class="studio-header-main">
        <div class="header-left">
          <div class="title-row">
            <h2 class="page-title">自动回复</h2>
            <div class="status-pill" :class="{ active: currentAccount?.settings?.auto_reply }">
              <span class="status-pulse-dot" />
              <span>{{ currentAccount?.settings?.auto_reply ? '自动回复运行中' : '自动回复已暂停' }}</span>
            </div>
          </div>
        </div>

        <div class="header-right">
          <!-- 账号切换器 -->
          <div v-if="accounts.list.length > 1" class="header-account-picker">
            <span class="picker-label">当前账号：</span>
            <el-select v-model="selectedAccountId" size="default" class="account-select">
              <el-option
                v-for="a in accounts.list"
                :key="a.id"
                :value="a.id"
                :label="a.remark || a.nickname || a.unb"
              >
                <div class="account-opt-item">
                  <span>{{ a.remark || a.nickname || a.unb }}</span>
                  <StatusTag :value="a.status" :map="accountStatusMap" />
                </div>
              </el-option>
            </el-select>
          </div>
          <div v-else-if="currentAccount" class="single-account-badge">
            <span class="badge-label">配置账号：</span>
            <span class="badge-name">{{ currentAccount.remark || currentAccount.nickname || currentAccount.unb }}</span>
            <StatusTag :value="currentAccount.status" :map="accountStatusMap" />
          </div>

          <!-- 总开关 -->
          <div v-if="currentAccount" class="master-switch-box">
            <span class="switch-label">总开关</span>
            <el-switch
              :model-value="currentAccount.settings?.auto_reply ?? false"
              :loading="busyAccount[`ar-${currentAccount.id}`]"
              inline-prompt
              active-text="开"
              inactive-text="关"
              size="default"
              @change="(v: string | number | boolean) => currentAccount && toggleAccountAutoReply(currentAccount, !!v)"
            />
          </div>

          <!-- 操作按钮与链接 -->
          <div class="header-action-group">
            <el-button :icon="Refresh" :loading="loading || docsLoading" circle @click="refreshAll" title="刷新数据" />
            <el-link type="info" :underline="false" class="nav-account-link" @click="router.push('/accounts')">
              账号管理 <el-icon><ArrowRight /></el-icon>
            </el-link>
          </div>
        </div>
      </div>
    </div>

    <!-- 核心功能区：清晰的 Tabs 分区结构 -->
    <div class="main-content-card">
      <el-tabs v-model="activeTab" class="rule-tabs" @tab-change="onTabChange">
        <!-- 标签页 1: 关键词规则 -->
        <el-tab-pane name="rules">
          <template #label>
            <div class="tab-label-inner">
              <el-icon><Tickets /></el-icon>
              <span>精准回复规则</span>
              <el-badge v-if="rules.length" :value="rules.length" class="tab-count-badge" type="info" />
            </div>
          </template>

          <div class="tab-body">
            <!-- 总开关关闭时的轻量警告提示 -->
            <div v-if="!currentAccount?.settings?.auto_reply" class="inline-warning-bar">
              <el-icon><WarningFilled /></el-icon>
              <span>账号自动回复总开关已关闭，所有精准回复规则暂不触发。</span>
              <el-button link type="primary" size="small" @click="currentAccount && toggleAccountAutoReply(currentAccount, true)">立即开启总开关</el-button>
            </div>

            <!-- 搜索与筛选工具条（内嵌精准回复开关） -->
            <div class="table-toolbar">
              <div class="toolbar-left">
                <el-input
                  v-model="ruleSearch"
                  placeholder="搜索规则名称、关键词或回复内容..."
                  :prefix-icon="Search"
                  clearable
                  class="search-input"
                />
                <el-select
                  v-if="accounts.list.length > 1"
                  v-model="ruleAccountFilter"
                  placeholder="按生效账号筛选"
                  clearable
                  class="account-filter-select"
                >
                  <el-option
                    v-for="a in accounts.list"
                    :key="a.id"
                    :value="a.id"
                    :label="a.remark || a.nickname || a.unb"
                  />
                </el-select>
              </div>

              <div class="toolbar-right">
                <div class="kw-switch-item">
                  <span class="kw-switch-label">精准回复：</span>
                  <el-switch
                    :model-value="currentAccount?.settings?.keyword_reply ?? false"
                    :loading="currentAccount ? busyAccount[`kw-${currentAccount.id}`] : false"
                    :disabled="!currentAccount || !currentAccount.settings?.auto_reply"
                    inline-prompt
                    active-text="开"
                    inactive-text="关"
                    size="default"
                    @change="(v: string | number | boolean) => currentAccount && toggleAccountKeywordReply(currentAccount, !!v)"
                  />
                </div>
                <el-button type="primary" :icon="Plus" @click="openCreate">新建规则</el-button>
              </div>
            </div>

            <!-- 空规则冷启动推荐卡片 -->
            <div v-if="!loading && !rules.length" class="empty-rules-hero">
              <div class="hero-top">
                <h3 class="hero-title">常用关键词回复预设模板</h3>
                <p class="hero-sub">快速启用常用应答规则，买家发送匹配词句时毫秒级自动回复</p>
              </div>

              <div class="preset-cards-grid">
                <div v-for="tpl in presetTemplates" :key="tpl.name" class="preset-card">
                  <div class="pc-head">
                    <span class="pc-name">{{ tpl.name }}</span>
                    <el-tag v-if="!tpl.safe" size="small" type="warning" effect="plain">需修改后再用</el-tag>
                  </div>
                  <div class="pc-kws">
                    <span class="pc-kw-label">触发关键词：</span>
                    <span v-for="k in tpl.keywords" :key="k" class="pc-kw-pill">{{ k }}</span>
                  </div>
                  <div class="pc-reply">“{{ tpl.reply }}”</div>
                  <div v-if="tpl.note" class="pc-note">{{ tpl.note }}</div>
                  <div class="pc-actions">
                    <el-button
                      v-if="tpl.safe"
                      size="small"
                      type="primary"
                      :icon="Check"
                      :loading="enablingPreset[tpl.name]"
                      @click="quickEnableTemplate(tpl)"
                    >
                      直接启用
                    </el-button>
                    <el-button v-else size="small" type="primary" plain @click="applyPreset(tpl)">填写后启用</el-button>
                    <el-button v-if="tpl.safe" size="small" link type="primary" @click="applyPreset(tpl)">修改后启用</el-button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 规则列表表格 -->
            <div v-else class="table-wrap">
              <el-table v-loading="loading" :data="filteredRules" class="rules-table" empty-text="未找到匹配的规则">
                <el-table-column label="规则名称" prop="name" min-width="140">
                  <template #default="{ row }">
                    <div class="rule-name-cell">
                      <span class="rule-name">
                        {{ row.name || '未命名规则' }}
                        <el-tag v-if="row.action === 'handoff'" size="small" type="warning" effect="plain">转人工</el-tag>
                      </span>
                      <span v-if="row.priority !== 0" class="priority-badge">优先度 {{ row.priority }}</span>
                    </div>
                  </template>
                </el-table-column>

                <el-table-column label="触发关键词" min-width="210">
                  <template #default="{ row }">
                    <div class="kw-wrap">
                      <el-tag v-for="k in row.keywords" :key="k" size="small" class="kw-tag" effect="light">{{ k }}</el-tag>
                    </div>
                    <div class="meta-row">
                      <span class="mode-tag">{{ matchLabel[row.match] || row.match }}</span>
                      <span class="dot-sep">·</span>
                      <span v-if="row.reply_once" class="once-tag">单买家只回1次</span>
                      <span v-else class="repeat-tag">每次触发</span>
                    </div>
                  </template>
                </el-table-column>

                <el-table-column label="自动回复内容" prop="reply" min-width="260" show-overflow-tooltip>
                  <template #default="{ row }">
                    <div class="reply-text">
                      <template v-if="row.reply">{{ row.reply }}</template>
                      <span v-else-if="row.action === 'handoff'" class="muted">不回复，暂停自动回复并通知你</span>
                    </div>
                    <div v-if="row.images?.length" class="muted smaller">附 {{ row.images.length }} 张图片</div>
                  </template>
                </el-table-column>

                <el-table-column label="生效范围" min-width="150">
                  <template #default="{ row }">
                    <div class="scope-account">{{ row.account_id ? accounts.nameOf(row.account_id) : '全部闲鱼账号' }}</div>
                    <div class="scope-item muted smaller">{{ row.item_id ? `商品: ${row.item_id}` : '全部商品通用' }}</div>
                  </template>
                </el-table-column>

                <el-table-column label="命中次数" prop="hits" width="105" sortable align="center">
                  <template #default="{ row }">
                    <el-tag size="small" :type="row.hits > 0 ? 'success' : 'info'" effect="plain">
                      {{ row.hits || 0 }} 次
                    </el-tag>
                  </template>
                </el-table-column>

                <el-table-column label="状态" width="80" align="center">
                  <template #default="{ row }">
                    <el-switch :model-value="row.enabled" size="small" @change="(v: string | number | boolean) => toggle(row as RuleOut, !!v)" />
                  </template>
                </el-table-column>

                <el-table-column label="操作" width="130" align="right" :fixed="isMobile ? undefined : 'right'">
                  <template #default="{ row }">
                    <div class="ops">
                      <el-button size="small" type="primary" plain @click="openEdit(row as RuleOut)">编辑</el-button>
                      <el-button size="small" type="danger" plain @click="remove(row as RuleOut)">删除</el-button>
                    </div>
                  </template>
                </el-table-column>
              </el-table>

              <div class="table-footer-bar">
                <span class="footer-tip">
                  <span class="tip-dot" />
                  共 {{ filteredRules.length }} 条规则（总计 {{ rules.length }} 条） · 累计触发 {{ rules.reduce((a, b) => a + (b.hits || 0), 0) }} 次 · 优先于 AI 执行
                </span>
                <el-button link type="primary" size="small" :icon="Plus" @click="openCreate">新建规则</el-button>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <!-- 标签页 2: AI 客服与知识库 -->
        <el-tab-pane name="ai">
          <template #label>
            <div class="tab-label-inner">
              <el-icon><MagicStick /></el-icon>
              <span>AI客服与知识库</span>
            </div>
          </template>

          <div class="tab-body">
            <!-- AI 回复模式控制条 -->
            <div class="ai-mode-hero-card">
              <div class="mode-hero-left">
                <div class="mode-title-wrap">
                  <span class="mode-hero-icon"><el-icon><MagicStick /></el-icon></span>
                  <span class="mode-hero-title">AI 回复模式</span>
                </div>
                <el-segmented
                  :model-value="currentAccount?.settings?.ai_mode ?? 'off'"
                  :options="aiModeOptions"
                  size="default"
                  class="ai-segmented-bar"
                  :disabled="!currentAccount || busyAccount[`ai-${currentAccount.id}`]"
                  @change="(v: string | number | boolean) => currentAccount && setAiMode(currentAccount, v as 'off' | 'suggest' | 'auto')"
                />
              </div>
              <div class="mode-hero-status">
                <template v-if="!currentAccount?.settings?.auto_reply && currentAccount?.settings?.ai_mode === 'auto'">
                  <div class="status-chip warning">
                    <el-icon><WarningFilled /></el-icon>
                    <span>总开关已关闭，AI 不会自动发送</span>
                    <el-button link type="primary" size="small" @click="currentAccount && toggleAccountAutoReply(currentAccount, true)">立即开启</el-button>
                  </div>
                </template>
                <template v-else-if="currentAccount?.settings?.ai_mode === 'auto'">
                  <div class="status-chip success">
                    <span class="status-chip-dot success" />
                    <span>全自动托管：未命中规则时，自动检索商品专属知识应答</span>
                  </div>
                </template>
                <template v-else-if="currentAccount?.settings?.ai_mode === 'suggest'">
                  <div class="status-chip info">
                    <span class="status-chip-dot info" />
                    <span>建议模式：在消息收件箱内实时生成建议，由你确认发送</span>
                  </div>
                </template>
                <template v-else>
                  <div class="status-chip muted">
                    <span class="status-chip-dot muted" />
                    <span>已关闭 AI 回复：仅通过关键词规则精准应答</span>
                  </div>
                </template>
              </div>
            </div>

            <!-- 主工作台：左右双栏平衡布局 -->
            <div class="ai-workbench">
              <!-- 左栏：店铺人设与语言风格 -->
              <div class="workbench-col-persona">
                <div class="workbench-card persona-card">
                  <div class="card-header">
                    <div class="header-title-box">
                      <span class="card-icon persona"><el-icon><User /></el-icon></span>
                      <div class="title-meta">
                        <h3 class="card-title">店铺人设与发货习惯</h3>
                        <span class="card-counter">{{ instructions.length }} / {{ MAX_INSTRUCTIONS }}</span>
                      </div>
                    </div>
                    <el-button
                      type="primary"
                      size="small"
                      :loading="savingInstr"
                      :disabled="!instrDirty"
                      @click="saveInstructions"
                    >
                      保存人设
                    </el-button>
                  </div>

                  <div class="persona-editor-box">
                    <el-input
                      v-model="instructions"
                      type="textarea"
                      :rows="11"
                      :maxlength="MAX_INSTRUCTIONS"
                      resize="none"
                      class="persona-textarea"
                      placeholder="用自然的语言设定 AI 的人设身份、发货安排及服务态度。&#10;&#10;例如：&#10;· 个人自用转让，商品均实拍，谢绝大刀&#10;· 语气亲切自然，可以适当称呼“宝”或“朋友”&#10;· 统一发中通快递，每天下午 17:00 前拍下当天发出&#10;· 电子卡券拍下系统自动发货，发出后不支持退换"
                    />
                  </div>

                  <div class="prompt-chips-section">
                    <div class="chips-label">常用人设快捷词（点击快速追加）</div>
                    <div class="chips-container">
                      <button
                        v-for="chip in promptChips"
                        :key="chip.label"
                        type="button"
                        class="modern-chip"
                        :title="chip.text"
                        @click="appendPromptChip(chip)"
                      >
                        <span class="chip-plus">+</span>
                        <span class="chip-text">{{ chip.label }}</span>
                      </button>
                    </div>
                  </div>

                  <div class="card-safe-guard">
                    <el-icon class="guard-icon"><Lock /></el-icon>
                    <span>底价保护与违规敏感词过滤享最高优先级，人设不会逾越安全底线。</span>
                  </div>
                </div>
              </div>

              <!-- 右栏：双支柱知识库体系（全店资料 + 宝贝专属一物一况） -->
              <div class="workbench-col-knowledge">
                <!-- 支柱 1: 全店通用资料库 -->
                <div class="workbench-card docs-card">
                  <div class="card-header">
                    <div class="header-title-box">
                      <span class="card-icon docs"><el-icon><Document /></el-icon></span>
                      <div class="title-meta">
                        <h3 class="card-title">全店通用资料库</h3>
                        <span class="card-tag">{{ shopDocs.length }} 份</span>
                      </div>
                    </div>
                    <div class="header-actions">
                      <el-radio-group v-model="uploadScope" size="small" class="scope-radio-group">
                        <el-radio-button value="account">本账号</el-radio-button>
                        <el-radio-button value="all">全店通用</el-radio-button>
                      </el-radio-group>
                      <el-upload :show-file-list="false" :accept="ACCEPT" :http-request="uploadShop" multiple>
                        <el-button size="small" :icon="Upload" class="doc-upload-btn">上传资料</el-button>
                      </el-upload>
                    </div>
                  </div>

                  <div v-loading="docsLoading" class="docs-scroll-area">
                    <div v-if="shopDocs.length" class="doc-cards-list">
                      <div v-for="d in shopDocs" :key="d.id" class="doc-item-row" :class="{ disabled: !d.enabled }">
                        <div class="doc-badge-icon">
                          <el-icon><Document /></el-icon>
                        </div>
                        <div class="doc-meta-info">
                          <div class="doc-filename ellipsis" :title="d.name">{{ d.name }}</div>
                          <div class="doc-sub-pills">
                            <span class="doc-char-pill">{{ d.chars.toLocaleString() }} 字</span>
                            <span class="doc-scope-pill">{{ d.account_id === null ? '全店通用' : '本账号专属' }}</span>
                          </div>
                        </div>
                        <div class="doc-actions">
                          <el-switch
                            :model-value="d.enabled"
                            size="small"
                            inline-prompt
                            active-text="开"
                            inactive-text="关"
                            @change="(v: string | number | boolean) => toggleDoc(d, !!v)"
                          />
                          <el-button link :icon="Delete" class="doc-del-btn" aria-label="删除" @click="removeDoc(d)" />
                        </div>
                      </div>
                    </div>
                    <div v-else class="empty-docs-box">
                      <el-icon class="empty-icon"><Document /></el-icon>
                      <span class="empty-title">暂未上传通用资料</span>
                      <span class="empty-hint">支持上传售后政策、常见问题或价目表（.txt / .md / .pdf / .docx）</span>
                    </div>
                  </div>
                </div>

                <!-- 支柱 2: 宝贝专属知识库（一物一况） -->
                <div class="workbench-card item-kb-card">
                  <div class="card-header">
                    <div class="header-title-box">
                      <span class="card-icon goods"><el-icon><Goods /></el-icon></span>
                      <div class="title-meta">
                        <h3 class="card-title">宝贝专属知识库</h3>
                        <span class="card-tag">一物一况</span>
                      </div>
                    </div>
                    <div class="header-actions">
                      <el-input
                        v-model="itemQuery"
                        size="small"
                        clearable
                        :prefix-icon="Search"
                        placeholder="搜索在售宝贝..."
                        class="item-search-input"
                      />
                    </div>
                  </div>

                  <div v-loading="itemsLoading" class="item-kb-scroll-area">
                    <div v-if="filteredItems.length" class="item-kb-list">
                      <div
                        v-for="it in filteredItems"
                        :key="it.id"
                        class="item-kb-row"
                        role="button"
                        tabindex="0"
                        @click="openKb(it)"
                        @keyup.enter="openKb(it)"
                      >
                        <el-image class="item-kb-thumb" :src="it.image_url" fit="cover" referrerpolicy="no-referrer" lazy>
                          <template #error>
                            <span class="thumb-fallback"><el-icon><Goods /></el-icon></span>
                          </template>
                        </el-image>
                        <div class="item-kb-info">
                          <div class="item-kb-title ellipsis" :title="it.title">{{ it.title }}</div>
                          <div class="item-kb-meta">
                            <span class="item-price">{{ fmtMoney(it.price) }}</span>
                            <span v-if="it.status !== 'on_sale'" class="item-status-tag">
                              {{ goodsStatusMap[it.status]?.label || it.status }}
                            </span>
                          </div>
                        </div>
                        <div class="item-kb-badges">
                          <span v-if="it.knowledge" class="status-badge has-kb">已设说明 · {{ it.knowledge.length }}字</span>
                          <span v-if="itemDocCount(it)" class="status-badge has-doc">{{ itemDocCount(it) }} 份资料</span>
                          <span v-if="!it.knowledge && !itemDocCount(it)" class="status-badge empty">未补充</span>
                        </div>
                        <el-button size="small" type="primary" plain class="item-edit-btn" @click.stop="openKb(it)">
                          配置知识
                        </el-button>
                      </div>
                    </div>
                    <div v-else-if="!itemsLoading" class="empty-items-box">
                      <template v-if="itemQuery">
                        <span class="empty-title">未找到与“{{ itemQuery }}”相关的宝贝</span>
                      </template>
                      <template v-else>
                        <el-icon class="empty-icon"><Goods /></el-icon>
                        <span class="empty-title">当前账号尚未同步商品</span>
                        <el-button
                          link
                          type="primary"
                          size="small"
                          @click="router.push({ path: '/goods/items', query: currentAccount ? { account_id: String(currentAccount.id) } : {} })"
                        >
                          前往商品管理同步商品
                        </el-button>
                      </template>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <!-- 标签页 3: 议价与安全底线 -->
        <el-tab-pane name="guard">
          <template #label>
            <div class="tab-label-inner">
              <el-icon><Coin /></el-icon>
              <span>议价与安全底线</span>
            </div>
          </template>

          <div class="tab-body">
            <div class="guard-studio-grid">
              <!-- 左侧：默认议价与让价规则 -->
              <div class="ai-column-panel guard-card">
                <div class="panel-header">
                  <div class="panel-title">
                    <span class="title-text">默认议价与让价规则</span>
                    <span class="title-desc">仅对未单独设置底价的宝贝生效；单独设置了底价的商品不受影响</span>
                  </div>
                  <el-button type="primary" size="small" :loading="savingGuard" :disabled="!guardDirty" @click="saveGuard">
                    保存议价设置
                  </el-button>
                </div>

                <el-form label-width="120px" :label-position="isMobile ? 'top' : 'right'" class="guard-form">
                  <el-form-item label="默认允许议价">
                    <el-switch v-model="guard.bargain_default" />
                    <span class="form-tip inline-tip">
                      关闭则咬死标价不让步；开启后允许 AI 在下方安全区间内与买家议价
                    </span>
                  </el-form-item>
                  <template v-if="guard.bargain_default">
                    <el-form-item label="最多让价">
                      <div class="bargain-row-wrap">
                        <el-input-number v-model="guard.bargain_max_percent" :min="1" :max="50" :step="1" />
                        <span class="unit">%</span>
                        <span class="unit-sep">且不超过</span>
                        <el-input-number v-model="guard.bargain_max_amount" :min="0" :step="10" placeholder="不限" />
                        <span class="unit">元</span>
                      </div>
                      <div class="form-tip">双重上限保障：百分比与封顶金额同时生效，取更严谨的一方</div>
                    </el-form-item>
                    <el-form-item label="最多议价轮次">
                      <div class="bargain-row-wrap">
                        <el-input-number v-model="guard.bargain_max_rounds" :min="1" :max="10" />
                        <span class="unit">轮，之后坚持最终一口价不再让步</span>
                      </div>
                      <div class="form-tip">达到上限后，AI 将温和而坚定地表示“已经是诚意底价，不能再少啦”</div>
                    </el-form-item>
                  </template>
                </el-form>
              </div>

              <!-- 右侧：平台合规防封与转人工机制 -->
              <div class="ai-column-panel safety-card">
                <div class="panel-header">
                  <div class="panel-title">
                    <span class="title-text">AI 敏感词过滤 (防封号)</span>
                    <span class="title-desc">命中敏感词的回复会在发出前自动拦截并重写，杜绝平台违规</span>
                  </div>
                  <el-button type="primary" size="small" :loading="savingGuard" :disabled="!guardDirty" @click="saveGuard">
                    保存禁用词
                  </el-button>
                </div>

                <div class="safety-body">
                  <div class="banned-words-wrap">
                    <el-input-tag
                      v-model="guard.ai_banned_words"
                      placeholder="输入违规敏感词后按回车，例如微信、电话、其他平台名、加V等"
                      save-on-blur
                      :max="100"
                    />
                    <div class="form-tip">
                      系统内置防封号过滤器：当 AI 输出中包含上述词汇时，直接触发静默拦截与重新组织语言。
                    </div>
                  </div>

                  <div class="handoff-rule-box">
                    <div class="box-title">
                      <el-icon class="box-icon text-warning"><WarningFilled /></el-icon>
                      <strong>纠纷与高风险咨询自动转人工</strong>
                    </div>
                    <p class="box-desc">
                      当买家消息涉及【售后纠纷、质量投诉、申请退款、恶意辱骂】等高敏感意图时，系统会自动暂停 AI 回复并通知你人工接管，保障店铺信誉与资金安全。
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>

      </el-tabs>
    </div>

    <!-- 编辑/新建规则弹窗 -->
    <el-dialog v-model="edit.open" :title="edit.id ? '编辑回复规则' : '新建回复规则'" width="580px" destroy-on-close>
      <el-form label-width="95px" :label-position="isMobile ? 'top' : 'right'">
        <el-form-item label="规则名称">
          <el-input v-model="edit.form.name" maxlength="64" placeholder="例如：常在线问候 / 快递时效说明" />
        </el-form-item>
        <el-form-item label="关键词" required>
          <el-input-tag v-model="edit.form.keywords" placeholder="输入关键词后按回车，买家消息包含任一即触发" save-on-blur />
        </el-form-item>
        <el-form-item label="匹配方式">
          <el-radio-group v-model="edit.form.match">
            <el-radio-button value="contains">包含关键词</el-radio-button>
            <el-radio-button value="exact">完全匹配</el-radio-button>
            <el-radio-button value="regex">正则表达式</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="命中后">
          <el-radio-group v-model="edit.form.action">
            <el-radio-button value="reply">自动回复</el-radio-button>
            <el-radio-button value="handoff">转人工</el-radio-button>
          </el-radio-group>
          <div v-if="edit.form.action === 'handoff'" class="form-tip">
            暂停这个会话的自动回复（时长按账号的「人工接管」设置），并通知你来回复。适合发票、定制、批量采购这类需要你本人处理的问题。
          </div>
        </el-form-item>
        <el-form-item :label="edit.form.action === 'handoff' ? '过渡话' : '回复内容'">
          <el-input
            v-model="edit.form.reply"
            type="textarea"
            :rows="4"
            maxlength="1000"
            show-word-limit
            :placeholder="
              edit.form.action === 'handoff'
                ? '可选：转人工前先回买家一句，例如「我确认一下，马上回你」；留空则不回复'
                : '买家触发该关键词后系统自动回复的内容'
            "
          />
        </el-form-item>
        <el-form-item v-if="edit.form.action === 'reply'" label="附带图片">
          <ImageUploader
            v-model="edit.form.images"
            v-model:uploading="imgUploading"
            :max="9"
            :pasteable="false"
            :allow-cover="false"
          />
          <div class="form-tip">文字之后按顺序发出，例如实拍图、尺码表、使用教程截图。只发图片时回复内容可以留空。</div>
        </el-form-item>
        <el-form-item label="生效账号">
          <el-select v-model="edit.form.account_id" clearable placeholder="全部闲鱼账号通用" class="w-full">
            <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
          </el-select>
        </el-form-item>
        <el-form-item label="指定商品">
          <el-input v-model="edit.form.item_id" placeholder="填写闲鱼商品 ID，留空对全部商品生效" clearable />
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="edit.form.priority" :min="-100" :max="100" />
          <div class="form-tip">
            多条规则同时命中时，先看适用范围：指定商品 &gt; 指定账号 &gt; 全部；范围相同才比优先级，数字大的优先。
          </div>
        </el-form-item>
        <el-form-item label="执行选项">
          <el-checkbox v-model="edit.form.reply_once">每个买家会话仅回复一次（避免刷屏）</el-checkbox>
          <el-checkbox v-model="edit.form.enabled">立即启用</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="edit.open = false">取消</el-button>
        <el-button type="primary" :loading="edit.saving" @click="saveRule">保存规则</el-button>
      </template>
    </el-dialog>

    <!-- 单件商品的知识库抽屉 -->
    <el-drawer v-model="kb.open" :size="isMobile ? '100%' : '560px'" title="宝贝专属知识（一物一况）" class="kb-drawer">
      <template v-if="kb.item">
        <div class="drawer-goods-hero">
          <el-image class="drawer-goods-thumb" :src="kb.item.image_url" fit="cover" referrerpolicy="no-referrer">
            <template #error><span class="thumb-fallback"><el-icon><Goods /></el-icon></span></template>
          </el-image>
          <div class="drawer-goods-details">
            <div class="drawer-goods-title" :title="kb.item.title">{{ kb.item.title }}</div>
            <div class="drawer-goods-meta">
              <span class="drawer-price">{{ fmtMoney(kb.item.price) }}</span>
              <span class="drawer-status-pill">{{ goodsStatusMap[kb.item.status]?.label || kb.item.status }}</span>
            </div>
          </div>
        </div>

        <div class="drawer-section">
          <div class="drawer-section-head">
            <div class="section-title-wrap">
              <span class="section-title">成色与专属说明</span>
              <span class="section-sub">成色细节、划痕瑕疵、电池健康度、随附配件等</span>
            </div>
            <span class="section-counter">{{ (kb.text || '').length }} / 8000</span>
          </div>
          <el-input
            v-model="kb.text"
            type="textarea"
            :rows="9"
            maxlength="8000"
            resize="none"
            class="drawer-textarea"
            placeholder="填写这件宝贝的专属细节。例如：&#10;· 成色 95 新，屏幕无划痕，边框右上角有一处轻微磕碰实拍可见&#10;· 电池健康度 88%，全原无拆修，功能均正常&#10;· 带原装包装盒与充电线，无发票&#10;买家咨询时，AI 优先精准引用此处，杜绝胡编乱造。"
          />
        </div>

        <div class="drawer-section">
          <div class="drawer-section-head">
            <div class="section-title-wrap">
              <span class="section-title">专属资料附件</span>
              <span class="section-sub">验机单、发票收据或官方说明书</span>
            </div>
            <el-upload :show-file-list="false" :accept="ACCEPT" :http-request="uploadItemDoc" multiple>
              <el-button size="small" :icon="Upload">上传文档</el-button>
            </el-upload>
          </div>
          <div class="drawer-doc-list">
            <div v-for="d in kbDocs" :key="d.id" class="doc-item-row" :class="{ disabled: !d.enabled }">
              <div class="doc-badge-icon">
                <el-icon><Document /></el-icon>
              </div>
              <div class="doc-meta-info">
                <div class="doc-filename ellipsis" :title="d.name">{{ d.name }}</div>
                <div class="doc-sub-pills">
                  <span class="doc-char-pill">{{ d.chars.toLocaleString() }} 字</span>
                </div>
              </div>
              <div class="doc-actions">
                <el-switch :model-value="d.enabled" size="small" @change="(v: string | number | boolean) => toggleDoc(d, !!v)" />
                <el-button link :icon="Delete" class="doc-del-btn" aria-label="删除" @click="removeDoc(d)" />
              </div>
            </div>
            <div v-if="!kbDocs.length" class="empty-drawer-docs">
              支持 txt、md、csv、pdf、docx 文档，AI 将自动分析提取知识
            </div>
          </div>
        </div>
      </template>
      <template #footer>
        <div class="drawer-footer-row">
          <el-button @click="kb.open = false">关闭</el-button>
          <el-button type="primary" :loading="kb.saving" :disabled="!kbDirty" @click="saveKb">保存专属知识</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.rules-page {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-3);
}

/* 顶部统一控制台横幅 */
.studio-header-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: 14px 18px;
  box-shadow: var(--xh-shadow-1);
}

.studio-header-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.header-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--xh-text);
  letter-spacing: -0.02em;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid #e2e8f0;
}

.status-pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #94a3b8;
}

.status-pill.active {
  background: var(--xh-primary-soft);
  color: var(--xh-primary-dark-2);
  border-color: var(--xh-primary-border);
}

.status-pill.active .status-pulse-dot {
  background: var(--xh-primary);
  box-shadow: 0 0 0 3px rgba(30, 158, 106, 0.2);
}


.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.header-account-picker {
  display: flex;
  align-items: center;
  gap: 6px;
}

.picker-label {
  font-size: 12px;
  color: var(--xh-muted);
  font-weight: 500;
}

.account-select {
  width: 170px;
}

.account-opt-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.single-account-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-sm);
}

.badge-label {
  font-size: 12px;
  color: var(--xh-muted);
}

.badge-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--xh-text);
}

.master-switch-box {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-sm);
}

.switch-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--xh-text);
}

.header-action-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.nav-account-link {
  font-size: 12px;
  color: var(--xh-muted);
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.nav-account-link:hover {
  color: var(--xh-primary);
}

/* 核心 Tab 容器 */
.main-content-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  box-shadow: var(--xh-shadow-1);
  overflow: hidden;
}

.rule-tabs :deep(.el-tabs__header) {
  margin: 0;
  padding: 0 16px;
  background: #fafbfc;
  border-bottom: 1px solid var(--xh-border);
}

.rule-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.rule-tabs :deep(.el-tabs__item) {
  height: 48px;
  line-height: 48px;
  font-size: var(--xh-fs-sm);
  font-weight: 500;
  color: var(--xh-text-2);
}

.rule-tabs :deep(.el-tabs__item.is-active) {
  color: var(--xh-primary);
  font-weight: 600;
}

.tab-label-inner {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  line-height: normal;
}

.tab-count-badge {
  display: inline-flex !important;
  align-items: center;
  justify-content: center;
  line-height: 1 !important;
  vertical-align: middle;
}

.tab-count-badge :deep(.el-badge__content) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  height: 16px;
  min-width: 16px;
  line-height: 1;
  padding: 0 4px;
  margin-left: 2px;
  border: none;
  box-sizing: border-box;
  vertical-align: unset;
  transform: none;
}

.tab-body {
  padding: 16px;
}

/* Tab 顶部功能控制条 */
/* 精准回复内嵌样式 */
.inline-warning-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding: 8px 14px;
  background: #fffbeb;
  border: 1px solid #fef3c7;
  border-radius: var(--xh-radius-sm);
  font-size: 12px;
  color: var(--xh-warning-text);
}

.kw-switch-item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-right: 4px;
}

.kw-switch-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--xh-text-2);
}

/* AI 运行模式紧凑切换栏 */
.ai-mode-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 14px;
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.strip-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mode-strip-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--xh-text);
}

.strip-right-desc {
  font-size: 12px;
  color: var(--xh-muted);
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}


/* 工具条 */
.table-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  gap: 12px;
  flex-wrap: wrap;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  max-width: 600px;
}

.search-input {
  flex: 1;
}

.account-filter-select {
  width: 170px;
}

/* 表格 */
.table-wrap {
  display: flex;
  flex-direction: column;
}

.rules-table {
  width: 100%;
}

.rule-name-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.rule-name {
  font-weight: 600;
  color: var(--xh-text);
  font-size: var(--xh-fs-sm);
}

.priority-badge {
  font-size: 11px;
  color: var(--xh-muted);
}

.kw-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.kw-tag {
  font-weight: 500;
}

.meta-row {
  margin-top: 4px;
  font-size: 11px;
  color: var(--xh-muted);
  display: flex;
  align-items: center;
}

.dot-sep {
  margin: 0 4px;
  color: var(--xh-muted);
}

.reply-text {
  font-size: var(--xh-fs-sm);
  color: var(--xh-text);
  line-height: 1.45;
}

.scope-account {
  font-size: var(--xh-fs-sm);
  font-weight: 500;
  color: var(--xh-text);
}

.ops {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

.table-footer-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--xh-border);
}

.tip-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
  background: var(--xh-success);
  margin-right: 6px;
  vertical-align: middle;
}

.footer-tip {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}

/* 空模板冷启动 */
.empty-rules-hero {
  padding: 20px;
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
}

.hero-top {
  text-align: center;
  margin-bottom: 20px;
}

.hero-title {
  font-size: var(--xh-fs-lg);
  font-weight: 700;
  color: var(--xh-text);
  margin: 0 0 6px;
}

.hero-sub {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
  margin: 0;
}

.preset-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.preset-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-sm);
  padding: 12px;
  display: flex;
  flex-direction: column;
}

.pc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--xh-fs-sm);
  font-weight: 600;
  margin-bottom: 6px;
}

.pc-kws {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.pc-kw-label {
  font-size: 11px;
  color: var(--xh-muted);
}

.pc-kw-pill {
  font-size: 11px;
  background: var(--xh-fill);
  padding: 1px 5px;
  border-radius: 4px;
  border: 1px solid var(--xh-border);
}

.pc-reply {
  font-size: var(--xh-fs-xs);
  color: var(--xh-text-2);
  background: var(--xh-fill);
  padding: 6px 8px;
  border-radius: 4px;
  border: 1px dashed var(--xh-border-strong);
  margin-bottom: 10px;
  flex: 1;
}

.pc-note {
  font-size: 11px;
  color: var(--xh-warning-text);
  margin-bottom: 8px;
}

.pc-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
}

/* ==========================================================================
   AI 客服与知识库 (AI Customer Service & Dual Knowledge Studio)
   ========================================================================== */

/* 顶部模式控制卡片 */
.ai-mode-hero-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 18px;
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  box-shadow: var(--xh-shadow-1);
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.mode-hero-left {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.mode-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mode-hero-icon {
  width: 28px;
  height: 28px;
  border-radius: var(--xh-radius-sm);
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
}

.mode-hero-title {
  font-size: var(--xh-fs-sm);
  font-weight: 700;
  color: var(--xh-text);
  letter-spacing: -0.01em;
}

.ai-segmented-bar :deep(.el-segmented__item) {
  font-size: var(--xh-fs-sm);
  font-weight: 500;
  padding: 4px 14px;
}

.ai-segmented-bar :deep(.el-segmented__item.is-selected) {
  font-weight: 600;
  color: var(--xh-primary-dark-2);
}

.mode-hero-status {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: var(--xh-radius-pill);
  font-size: 12px;
  font-weight: 500;
  border: 1px solid transparent;
}

.status-chip.warning {
  background: #fffbeb;
  color: #b45309;
  border-color: #fef3c7;
}

.status-chip.success {
  background: #f0fdf4;
  color: #15803d;
  border-color: #bbf7d0;
}

.status-chip.info {
  background: #eff6ff;
  color: #1d4ed8;
  border-color: #bfdbfe;
}

.status-chip.muted {
  background: #f8fafc;
  color: #64748b;
  border-color: #e2e8f0;
}

.status-chip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.status-chip-dot.success {
  background: #16a34a;
  box-shadow: 0 0 0 2px rgba(22, 163, 74, 0.2);
}

.status-chip-dot.info {
  background: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}

.status-chip-dot.muted {
  background: #94a3b8;
}

/* 核心工作台两栏布局 */
.ai-workbench {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
  gap: 16px;
  align-items: stretch;
}

.workbench-col-persona {
  display: flex;
  flex-direction: column;
}

.workbench-col-knowledge {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 工作台统一卡片规范 */
.workbench-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: 16px 18px;
  box-shadow: var(--xh-shadow-1);
  display: flex;
  flex-direction: column;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.workbench-card:hover {
  border-color: var(--xh-border-strong);
}

.persona-card {
  height: 100%;
}

.workbench-card .card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.header-title-box {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-icon {
  width: 28px;
  height: 28px;
  border-radius: var(--xh-radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  flex-shrink: 0;
}

.card-icon.persona {
  background: #ecfdf5;
  color: #059669;
}

.card-icon.docs {
  background: #eff6ff;
  color: #2563eb;
}

.card-icon.goods {
  background: #f5f3ff;
  color: #7c3aed;
}

.title-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-title {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--xh-text);
  letter-spacing: -0.01em;
}

.card-counter,
.card-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: var(--xh-radius-pill);
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid #e2e8f0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.scope-radio-group :deep(.el-radio-button__inner) {
  padding: 4px 10px;
  font-size: 11px;
}

.item-search-input {
  width: 170px;
}

/* 店铺人设编辑器 */
.persona-editor-box {
  flex: 1;
  display: flex;
  flex-direction: column;
  margin-bottom: 12px;
}

.persona-textarea :deep(.el-textarea__inner) {
  font-family: inherit;
  font-size: 13px;
  line-height: 1.65;
  padding: 12px 14px;
  background: #fafbfc;
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-sm);
  color: var(--xh-text);
  transition: all 0.2s ease;
}

.persona-textarea :deep(.el-textarea__inner):focus {
  background: #ffffff;
  border-color: var(--xh-primary);
  box-shadow: 0 0 0 3px rgba(30, 158, 106, 0.12);
}

/* 常用人设快捷词栏 */
.prompt-chips-section {
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px dashed var(--xh-border);
  margin-bottom: 12px;
}

.chips-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--xh-muted);
  margin-bottom: 8px;
}

.chips-container {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.modern-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: var(--xh-radius-pill);
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: var(--xh-text-2);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.modern-chip:hover {
  background: var(--xh-primary-soft);
  border-color: var(--xh-primary-border);
  color: var(--xh-primary);
  transform: translateY(-1px);
}

.modern-chip:active {
  transform: translateY(0);
}

.chip-plus {
  font-size: 11px;
  font-weight: 700;
  opacity: 0.6;
}

.card-safe-guard {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #64748b;
  background: #f8fafc;
  padding: 6px 10px;
  border-radius: var(--xh-radius-sm);
  border: 1px solid #f1f5f9;
}

.guard-icon {
  color: #059669;
  font-size: 14px;
  flex-shrink: 0;
}

/* 通用资料与宝贝知识列表滚动区 */
.docs-scroll-area {
  min-height: 120px;
  max-height: 180px;
  overflow-y: auto;
}

.doc-cards-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.doc-item-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: var(--xh-radius-sm);
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  transition: all 0.15s ease;
}

.doc-item-row:hover {
  background: #f1f5f9;
  border-color: #e2e8f0;
}

.doc-item-row.disabled {
  opacity: 0.55;
}

.doc-badge-icon {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: #eff6ff;
  color: #3b82f6;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  flex-shrink: 0;
}

.doc-meta-info {
  flex: 1;
  min-width: 0;
}

.doc-filename {
  font-size: 12px;
  font-weight: 600;
  color: var(--xh-text);
}

.doc-sub-pills {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
  font-size: 11px;
  color: var(--xh-muted);
}

.doc-char-pill,
.doc-scope-pill {
  display: inline-block;
}

.doc-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.doc-del-btn {
  color: var(--xh-muted);
}

.doc-del-btn:hover {
  color: var(--xh-danger);
}

.empty-docs-box,
.empty-items-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px 16px;
  text-align: center;
  color: var(--xh-muted);
  gap: 4px;
}

.empty-docs-box .empty-icon,
.empty-items-box .empty-icon {
  font-size: 26px;
  color: #cbd5e1;
  margin-bottom: 2px;
}

.empty-docs-box .empty-title,
.empty-items-box .empty-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--xh-text-2);
}

.empty-docs-box .empty-hint {
  font-size: 11px;
  color: var(--xh-muted);
}

/* 宝贝专属知识列表 */
.item-kb-scroll-area {
  min-height: 160px;
  max-height: 240px;
  overflow-y: auto;
}

.item-kb-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.item-kb-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--xh-radius-sm);
  border: 1px solid transparent;
  transition: all 0.15s ease;
  cursor: pointer;
}

.item-kb-row:hover {
  background: #f8fafc;
  border-color: #e2e8f0;
}

.item-kb-thumb {
  width: 40px;
  height: 40px;
  border-radius: 6px;
  background: #f1f5f9;
  border: 1px solid var(--xh-border);
  flex-shrink: 0;
}

.thumb-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  font-size: 18px;
}

.item-kb-info {
  flex: 1;
  min-width: 0;
}

.item-kb-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--xh-text);
  line-height: 1.4;
}

.item-kb-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}

.item-price {
  font-size: 12px;
  font-weight: 700;
  color: var(--xh-price);
}

.item-status-tag {
  font-size: 10px;
  color: var(--xh-muted);
  background: #f1f5f9;
  padding: 0 4px;
  border-radius: 2px;
}

.item-kb-badges {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.status-badge {
  font-size: 11px;
  font-weight: 500;
  padding: 1px 7px;
  border-radius: 4px;
  white-space: nowrap;
}

.status-badge.has-kb {
  background: #dcfce7;
  color: #15803d;
  border: 1px solid #bbf7d0;
}

.status-badge.has-doc {
  background: #dbeafe;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}

.status-badge.empty {
  background: #f1f5f9;
  color: #94a3b8;
}

.item-edit-btn {
  flex-shrink: 0;
  font-size: 11px;
}

/* 抽屉样式 */
.drawer-goods-hero {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: #f8fafc;
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-sm);
  margin-bottom: 16px;
}

.drawer-goods-thumb {
  width: 56px;
  height: 56px;
  border-radius: 6px;
  background: #f1f5f9;
  border: 1px solid var(--xh-border);
  flex-shrink: 0;
}

.drawer-goods-details {
  flex: 1;
  min-width: 0;
}

.drawer-goods-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--xh-text);
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-bottom: 4px;
}

.drawer-goods-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.drawer-price {
  font-size: 14px;
  font-weight: 700;
  color: var(--xh-price);
}

.drawer-status-pill {
  font-size: 11px;
  color: var(--xh-muted);
}

.drawer-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 18px;
}

.drawer-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.section-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.section-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--xh-text);
}

.section-sub {
  font-size: 11px;
  color: var(--xh-muted);
}

.section-counter {
  font-size: 11px;
  color: var(--xh-muted);
}

.drawer-textarea :deep(.el-textarea__inner) {
  font-family: inherit;
  font-size: 13px;
  line-height: 1.6;
  padding: 10px 12px;
  background: #fafbfc;
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-sm);
}

.drawer-textarea :deep(.el-textarea__inner):focus {
  background: #ffffff;
  border-color: var(--xh-primary);
  box-shadow: 0 0 0 3px rgba(30, 158, 106, 0.12);
}

.drawer-doc-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 48px;
}

.empty-drawer-docs {
  padding: 14px;
  text-align: center;
  color: var(--xh-muted);
  font-size: 11px;
  background: #f8fafc;
  border: 1px dashed var(--xh-border);
  border-radius: var(--xh-radius-sm);
}

.drawer-footer-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 1080px) {
  .ai-workbench {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .ai-mode-hero-card {
    flex-direction: column;
    align-items: flex-start;
  }
  .item-kb-badges {
    display: none;
  }
}

/* 人设面板与通用面板卡片 */
.ai-column-panel {
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: 16px;
  background: #ffffff;
  display: flex;
  flex-direction: column;
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 10px;
}

.panel-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.title-text {
  font-size: var(--xh-fs-sm);
  font-weight: 700;
  color: var(--xh-text);
}

.title-desc {
  font-size: 11px;
  color: var(--xh-muted);
}



/* 议价与安全底线 Tab */
.guard-studio-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  align-items: start;
}

@media (max-width: 992px) {
  .guard-studio-grid {
    grid-template-columns: 1fr;
  }
}

.guard-form :deep(.el-form-item) {
  margin-bottom: 12px;
}

.bargain-row-wrap {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}

.unit-sep {
  margin: 0 8px;
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}

.unit {
  margin: 0 6px;
  font-size: var(--xh-fs-sm);
  color: var(--xh-text-2);
}

.inline-tip {
  margin: 0 0 0 8px;
}

.form-tip {
  font-size: 11px;
  color: var(--xh-muted);
  line-height: 1.5;
  margin-top: 4px;
}

.safety-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.banned-words-wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.handoff-rule-box {
  background: #f8fafc;
  border: 1px dashed var(--xh-border-strong);
  border-radius: var(--xh-radius-sm);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.box-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--xh-text);
}

.box-icon {
  font-size: 16px;
  color: var(--xh-warning-text);
}

.box-desc {
  margin: 0;
  font-size: 12px;
  color: var(--xh-muted);
  line-height: 1.5;
}

.w-full {
  width: 100%;
}
</style>
