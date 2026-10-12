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
  MagicStick,
  Plus,
  Refresh,
  Search,
  Tickets,
  Upload,
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
import { useAccountsStore } from '@/stores/accounts'
import { useMobile } from '@/composables/useMobile'
import StatusTag from '@/components/StatusTag.vue'
import ImageUploader from '@/components/ImageUploader.vue'
import { accountStatusMap } from '@/utils/format'

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

function goToGoodsKnowledge() {
  router.push({
    path: '/goods/items',
    query: selectedAccountId.value ? { account_id: String(selectedAccountId.value) } : {},
  })
}

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
  { label: '建议', value: 'suggest' },
  { label: '自动发送', value: 'auto' },
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
          ? 'AI 会在收件箱给出回复建议，由你确认后发送'
          : 'AI 回复已开启：关键词没命中时由 AI 自动回复',
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
  '学生党自用出闲置，周末发货',
  '说话亲切自然，可以称呼“宝”，不机械生硬',
  '统一发中通，偏远地区（新疆西藏）不包邮',
  '电子资料拍下后自动发货，发出后不支持退换',
  '支持验货宝，所见即所得',
  '不接大刀，诚心要可小幅优惠',
]

function appendPromptChip(chip: string) {
  const current = instructions.value.trim()
  if (!current) {
    instructions.value = `· ${chip}`
  } else {
    instructions.value = `${current}\n· ${chip}`
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
const uploadScope = ref<'all' | 'account'>('all')
const ACCEPT = '.txt,.md,.csv,.pdf,.docx'

async function loadDocs() {
  docsLoading.value = true
  try {
    docs.value = await listKnowledgeDocs()
  } finally {
    docsLoading.value = false
  }
}

const visibleDocs = computed(() =>
  docs.value.filter((d) => d.account_id === null || d.account_id === selectedAccountId.value),
)

async function upload(opts: UploadRequestOptions) {
  const d = await uploadKnowledgeDoc(opts.file, uploadScope.value === 'account' ? (selectedAccountId.value ?? null) : null)
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
  await Promise.all([loadRules(), loadDocs(), accounts.load().catch(() => undefined)])
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
          <p class="page-subtitle">
            毫秒级精准命中关键词 · 未命中由 AI 结合【宝贝专属知识】与【店铺人设】智能应答
          </p>
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
            <!-- AI 运行模式紧凑切换栏 -->
            <div class="ai-mode-strip">
              <div class="strip-left">
                <span class="mode-strip-label">AI 回复模式：</span>
                <el-segmented
                  :model-value="currentAccount?.settings?.ai_mode ?? 'off'"
                  :options="aiModeOptions"
                  size="default"
                  :disabled="!currentAccount || busyAccount[`ai-${currentAccount.id}`]"
                  @change="(v: string | number | boolean) => currentAccount && setAiMode(currentAccount, v as 'off' | 'suggest' | 'auto')"
                />
              </div>
              <div class="strip-right-desc">
                <template v-if="!currentAccount?.settings?.auto_reply && currentAccount?.settings?.ai_mode === 'auto'">
                  <span class="desc-warning">
                    <el-icon><WarningFilled /></el-icon> 总开关已关闭，全自动需开启总开关
                  </span>
                  <el-button link type="primary" size="small" @click="currentAccount && toggleAccountAutoReply(currentAccount, true)">开启总开关</el-button>
                </template>
                <template v-else-if="currentAccount?.settings?.ai_mode === 'auto'">
                  <span class="status-tag-lead text-success">全自动智能托管</span> · 关键词未命中时，AI 自动检索【对应宝贝专属知识】并结合【店铺人设】直接回复买家
                </template>
                <template v-else-if="currentAccount?.settings?.ai_mode === 'suggest'">
                  <span class="status-tag-lead text-primary">人工把关模式</span> · 收到咨询后在收件箱生成建议回复卡片，由人工一键确认后再发送
                </template>
                <template v-else>
                  <span class="status-tag-lead text-muted">AI 回复已关闭</span> · 仅按精准规则回复，未命中的消息不调用 AI 大模型
                </template>
              </div>
            </div>

            <!-- 左右分栏工作台 (左：人设发货；右：双核知识库) -->
            <div class="ai-studio-grid">
              <!-- 左侧 54%：店铺人设与全局回复习惯 -->
              <div class="studio-col-left">
                <div class="ai-column-panel persona-panel">
                  <div class="panel-header">
                    <div class="panel-title">
                      <span class="title-text">店铺人设与发货习惯</span>
                      <span class="title-desc">定义 AI 的身份、语气、快递与截单时间（关键词未命中时生效）</span>
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

                  <!-- 快捷人设词签 -->
                  <div class="prompt-chips-bar">
                    <span class="chips-title">参考词：</span>
                    <div class="chips-list">
                      <span
                        v-for="chip in promptChips"
                        :key="chip"
                        class="prompt-chip"
                        @click="appendPromptChip(chip)"
                      >
                        + {{ chip }}
                      </span>
                    </div>
                  </div>

                  <div class="textarea-wrap">
                    <el-input
                      v-model="instructions"
                      type="textarea"
                      :rows="8"
                      :maxlength="MAX_INSTRUCTIONS"
                      show-word-limit
                      placeholder="用自然的语言告诉 AI 你的身份、店铺规矩和回复习惯，例如：&#10;· 我是个人自用转让，商品均实拍，谢绝恶意砍价&#10;· 回复亲切自然，可以适当称呼“宝”或“朋友”&#10;· 统一发中通快递，每天下午 5 点前拍下当天发出&#10;· 电子卡券拍下系统自动发货，发出后不支持退换"
                    />
                  </div>

                  <div class="panel-foot-notice">
                    <el-icon><WarningFilled /></el-icon>
                    <span>保障底线：商品专属底价与违规拦截始终最高优先，人设中写了也不会突破。</span>
                  </div>
                </div>
              </div>

              <!-- 右侧 46%：双核知识库体系 -->
              <div class="studio-col-right">
                <!-- 卡片 1: 核心生效层 · 商品专属知识库 (针对具体宝贝) -->
                <div class="arch-card item-kb-card">
                  <div class="arch-card-header">
                    <div class="arch-tag-row">
                      <el-tag type="success" size="small" effect="dark" class="arch-badge">核心生效层</el-tag>
                      <span class="arch-subtag">针对每个在售宝贝 · 自动精准命中</span>
                    </div>
                    <div class="arch-title">
                      <el-icon class="arch-title-icon"><Goods /></el-icon>
                      <span>商品专属知识库 (一物一况)</span>
                    </div>
                  </div>

                  <div class="arch-body">
                    <div class="arch-concept-box">
                      <p class="concept-point">
                        <strong>🎯 一物一况专属应答：</strong>成色划痕、电池健康度、是否在保、正品发票、随附配件等。
                      </p>
                      <p class="concept-point">
                        <strong>🛡️ 独立底价保护：</strong>商品中心可为每个宝贝单独设底价，AI 绝不越界。
                      </p>
                    </div>

                    <div class="arch-explain-text">
                      买家咨询特定宝贝时，AI <b>自动优先检索该商品的专属知识</b>，彻底杜绝多宝贝串款幻觉。
                    </div>
                  </div>

                  <div class="arch-footer">
                    <el-button type="primary" :icon="Goods" class="w-full" @click="goToGoodsKnowledge">
                      前往【商品管理】维护宝贝专属知识
                    </el-button>
                    <div class="arch-footer-tip">
                      在商品列表中点击任一商品的「知识库」即可补充最高 8000 字专属说明
                    </div>
                  </div>
                </div>

                <!-- 卡片 2: 全局辅助层 · 全店通用补充说明书 -->
                <div class="arch-card global-doc-card">
                  <div class="arch-card-header">
                    <div class="arch-tag-row">
                      <el-tag type="info" size="small" effect="plain" class="arch-badge">全局补充层</el-tag>
                      <span class="arch-subtag">全店/账号共享 · 兜底辅助 (可选)</span>
                    </div>
                    <div class="arch-title">
                      <el-icon class="arch-title-icon"><Document /></el-icon>
                      <span>全店通用补充说明书</span>
                    </div>
                  </div>

                  <div class="arch-body">
                    <div class="doc-upload-strip">
                      <div class="scope-picker">
                        <span class="scope-label">归属：</span>
                        <el-radio-group v-model="uploadScope" size="small">
                          <el-radio-button value="all">通用</el-radio-button>
                          <el-radio-button value="account">当前</el-radio-button>
                        </el-radio-group>
                      </div>
                      <el-upload :show-file-list="false" :accept="ACCEPT" :http-request="upload" multiple>
                        <el-button size="small" type="primary" plain :icon="Upload">上传文档</el-button>
                      </el-upload>
                    </div>

                    <div v-loading="docsLoading" class="docs-mini-list-wrap">
                      <div v-if="!visibleDocs.length" class="empty-docs-compact">
                        <el-icon class="empty-docs-icon"><Document /></el-icon>
                        <div class="empty-text">暂无全局通用文档（非必须，宝贝知识通常已足够）</div>
                      </div>

                      <div v-else class="docs-mini-list">
                        <div v-for="d in visibleDocs" :key="d.id" class="doc-card-compact" :class="{ disabled: !d.enabled }">
                          <el-icon class="doc-file-icon"><Document /></el-icon>
                          <div class="doc-details">
                            <div class="doc-title-row">
                              <span class="doc-name" :title="d.name">{{ d.name }}</span>
                              <el-tag size="small" :type="d.account_id === null ? 'info' : 'primary'" effect="plain">
                                {{ d.account_id === null ? '通用' : '当前' }}
                              </el-tag>
                            </div>
                            <div class="doc-sub">{{ d.chars.toLocaleString() }} 字 · {{ d.preview || '已建立索引' }}</div>
                          </div>

                          <div class="doc-actions">
                            <el-switch
                              :model-value="d.enabled"
                              size="small"
                              @change="(v: string | number | boolean) => toggleDoc(d, !!v)"
                            />
                            <el-button link type="danger" :icon="Delete" @click="removeDoc(d)" />
                          </div>
                        </div>
                      </div>
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

.page-subtitle {
  margin: 0;
  font-size: 12px;
  color: var(--xh-muted);
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

.status-tag-lead {
  font-weight: 600;
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

/* AI 左右分栏工作台 */
.ai-studio-grid {
  display: grid;
  grid-template-columns: 54% 46%;
  gap: 16px;
  align-items: start;
}

@media (max-width: 992px) {
  .ai-studio-grid {
    grid-template-columns: 1fr;
  }
}

.studio-col-left {
  display: flex;
  flex-direction: column;
}

.studio-col-right {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* 知识库卡片 */
.arch-card {
  background: #ffffff;
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  transition: all 0.2s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.item-kb-card {
  border-color: #bbf7d0;
  background: linear-gradient(180deg, #f0fdf4 0%, #ffffff 65px);
}

.item-kb-card:hover {
  box-shadow: 0 4px 12px rgba(22, 163, 74, 0.08);
  border-color: #86efac;
}

.global-doc-card {
  background: #ffffff;
}

.arch-card-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 10px;
  border-bottom: 1px solid var(--xh-border);
  padding-bottom: 8px;
}

.arch-tag-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.arch-badge {
  font-weight: 600;
}

.arch-subtag {
  font-size: 11px;
  color: var(--xh-muted);
}

.arch-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 700;
  color: var(--xh-text);
}

.arch-title-icon {
  font-size: 16px;
  color: var(--xh-primary);
}

.global-doc-card .arch-title-icon {
  color: #3b82f6;
}

.arch-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.arch-concept-box {
  background: rgba(255, 255, 255, 0.9);
  border: 1px dashed #86efac;
  border-radius: var(--xh-radius-sm);
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.concept-point {
  margin: 0;
  font-size: var(--xh-fs-xs);
  color: var(--xh-text-2);
  line-height: 1.45;
}

.concept-point strong {
  color: var(--xh-text);
}

.arch-explain-text {
  font-size: 11px;
  color: var(--xh-muted);
  line-height: 1.45;
}

.arch-footer {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.arch-footer-tip {
  font-size: 11px;
  color: var(--xh-muted);
  text-align: center;
}

/* 全店文档卡片内容 */
.doc-upload-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.scope-picker {
  display: flex;
  align-items: center;
  gap: 4px;
}

.scope-label {
  font-size: 11px;
  color: var(--xh-muted);
}

.docs-mini-list-wrap {
  flex: 1;
  min-height: 90px;
  display: flex;
  flex-direction: column;
}

.empty-docs-compact {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 14px 10px;
  background: #f8fafc;
  border: 1px dashed var(--xh-border);
  border-radius: var(--xh-radius-sm);
  color: var(--xh-muted);
  text-align: center;
  gap: 4px;
}

.empty-docs-icon {
  font-size: 20px;
  color: var(--xh-border-strong);
}

.empty-text {
  font-size: 11px;
}

.docs-mini-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 140px;
  overflow-y: auto;
}

.doc-card-compact {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  background: #f8fafc;
  border: 1px solid var(--xh-border);
  border-radius: 6px;
  transition: all 0.15s ease;
}

.doc-card-compact.disabled {
  opacity: 0.6;
}

.doc-file-icon {
  font-size: 16px;
  color: var(--xh-primary);
  flex-shrink: 0;
}

.doc-details {
  flex: 1;
  min-width: 0;
}

.doc-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.doc-name {
  font-size: var(--xh-fs-xs);
  font-weight: 500;
  color: var(--xh-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-sub {
  font-size: 11px;
  color: var(--xh-muted);
  margin-top: 1px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
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

.prompt-chips-bar {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: 8px;
}

.chips-title {
  font-size: 11px;
  color: var(--xh-muted);
  flex-shrink: 0;
  margin-top: 2px;
}

.chips-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.prompt-chip {
  font-size: 11px;
  background: #f8fafc;
  border: 1px solid var(--xh-border);
  padding: 2px 7px;
  border-radius: 4px;
  cursor: pointer;
  color: var(--xh-text-2);
  transition: all 0.15s ease;
}

.prompt-chip:hover {
  border-color: var(--xh-primary);
  color: var(--xh-primary);
  background: var(--xh-primary-soft);
}

.textarea-wrap {
  flex: 1;
}

.panel-foot-notice {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  font-size: 11px;
  color: var(--xh-warning-text);
  background: #fffbeb;
  padding: 6px 10px;
  border-radius: 4px;
  border: 1px solid #fef3c7;
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
