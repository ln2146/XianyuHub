<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type UploadRequestOptions } from 'element-plus'
import {
  Check,
  Delete,
  Document,
  MagicStick,
  Plus,
  Refresh,
  Search,
  Setting,
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
import { accountStatusMap } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const accounts = useAccountsStore()
const isMobile = useMobile()

// ---------------------------------------------------------------- Tab 状态
const activeTab = ref<'rules' | 'ai'>('rules')
if (route.query.tab && ['rules', 'ai'].includes(String(route.query.tab))) {
  activeTab.value = route.query.tab as 'rules' | 'ai'
}

watch(
  () => route.query.tab,
  (t) => {
    if (t && ['rules', 'ai'].includes(String(t))) {
      activeTab.value = t as 'rules' | 'ai'
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
  reply: '',
  priority: 0,
  reply_once: false,
  enabled: true,
})

const edit = reactive({ open: false, saving: false, id: null as number | null, form: empty() })

function openCreate() {
  Object.assign(edit, { open: true, id: null, form: empty() })
}

function openEdit(r: RuleOut) {
  const { id: _id, hits: _hits, ...rest } = r
  Object.assign(edit, { open: true, id: r.id, form: { ...rest, keywords: [...r.keywords] } })
}

function toIn(r: RuleOut): RuleIn {
  const { id: _id, hits: _hits, ...rest } = r
  return rest
}

const PLACEHOLDER = /【[^】]*】/

async function saveRule() {
  const f = edit.form
  if (!f.keywords.length) return ElMessage.warning('至少需要一个关键词')
  if (!f.reply.trim()) return ElMessage.warning('请填写回复内容')
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
    const body: RuleIn = { ...f, item_id: f.item_id?.trim() || null }
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
      reply: tpl.reply,
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
    <!-- 顶部标题与快捷操作 -->
    <div class="page-head">
      <div class="head-left">
        <h2>消息中心 · 自动回复</h2>
        <span class="head-subtitle">关键词规则优先命中；未命中时由 AI 结合店铺人设与知识库资料智能应答</span>
      </div>
      <div class="toolbar">
        <el-button :icon="Refresh" :loading="loading || docsLoading" round @click="refreshAll">刷新</el-button>
        <el-button v-if="activeTab === 'rules'" type="primary" :icon="Plus" round @click="openCreate">新建规则</el-button>
      </div>
    </div>

    <!-- 账号回复策略概览条 (精简横向卡片，去除凌乱感) -->
    <div class="account-strip-card">
      <div class="strip-header">
        <div class="strip-title">
          <el-icon class="title-icon"><Setting /></el-icon>
          <span>账号回复策略</span>
          <span class="strip-tip">总开关关闭时该账号不回复任何消息；AI 回复在关键词未命中时代替人工</span>
        </div>
        <el-link type="primary" class="nav-link" @click="router.push('/accounts')">
          前往账号配置 <el-icon><ArrowRight /></el-icon>
        </el-link>
      </div>

      <div v-if="!accounts.list.length" class="empty-acc-banner">
        尚未添加闲鱼账号，请先在「账号配置」中接入账号以启用自动回复。
      </div>

      <div v-else class="acc-capsule-list">
        <div
          v-for="a in accounts.list"
          :key="a.id"
          class="acc-capsule"
          :class="{ active: selectedAccountId === a.id }"
          @click="selectedAccountId = a.id"
        >
          <div class="capsule-profile">
            <div class="capsule-avatar">{{ (a.remark || a.nickname || '闲')[0] }}</div>
            <div class="capsule-info">
              <div class="capsule-name" :title="a.remark || a.nickname || a.unb">
                {{ a.remark || a.nickname || a.unb }}
              </div>
              <div class="capsule-status">
                <StatusTag :value="a.status" :map="accountStatusMap" />
                <span v-if="!a.settings?.auto_reply" class="status-warning">
                  <el-icon><WarningFilled /></el-icon> 总开关已关
                </span>
              </div>
            </div>
          </div>

          <div class="capsule-controls" @click.stop>
            <div class="ctrl-group">
              <span class="ctrl-label">总开关</span>
              <el-switch
                :model-value="a.settings?.auto_reply ?? false"
                :loading="busyAccount[`ar-${a.id}`]"
                inline-prompt
                active-text="开"
                inactive-text="关"
                size="small"
                @change="(v: string | number | boolean) => toggleAccountAutoReply(a, !!v)"
              />
            </div>

            <div class="ctrl-group">
              <span class="ctrl-label">关键词</span>
              <el-switch
                :model-value="a.settings?.keyword_reply ?? false"
                :loading="busyAccount[`kw-${a.id}`]"
                :disabled="!a.settings?.auto_reply"
                inline-prompt
                active-text="开"
                inactive-text="关"
                size="small"
                @change="(v: string | number | boolean) => toggleAccountKeywordReply(a, !!v)"
              />
            </div>

            <div class="ctrl-group ctrl-ai">
              <span class="ctrl-label">AI 模式</span>
              <el-segmented
                :model-value="a.settings?.ai_mode ?? 'off'"
                :options="aiModeOptions"
                size="small"
                :disabled="busyAccount[`ai-${a.id}`]"
                @change="(v: string | number | boolean) => setAiMode(a, v as 'off' | 'suggest' | 'auto')"
              />
            </div>
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
              <span>关键词精准规则</span>
              <el-badge v-if="rules.length" :value="rules.length" class="tab-count-badge" type="info" />
            </div>
          </template>

          <div class="tab-body">
            <!-- 搜索与筛选工具条 -->
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
                      <span class="rule-name">{{ row.name || '未命名规则' }}</span>
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
                    <div class="reply-text">{{ row.reply }}</div>
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

        <!-- 标签页 2: AI 设定与知识库 -->
        <el-tab-pane name="ai">
          <template #label>
            <div class="tab-label-inner">
              <el-icon><MagicStick /></el-icon>
              <span>AI 人设与知识库</span>
            </div>
          </template>

          <div class="tab-body">
            <!-- 账号切换器（多账号时置顶展示） -->
            <div v-if="accounts.list.length > 1" class="tab-account-selector">
              <span class="selector-label">当前配置账号：</span>
              <el-radio-group v-model="selectedAccountId" size="small">
                <el-radio-button v-for="a in accounts.list" :key="a.id" :value="a.id">
                  {{ a.remark || a.nickname || a.unb }}
                </el-radio-button>
              </el-radio-group>
            </div>

            <!-- 两列对称排布：左人设说明，右知识库文件 -->
            <div class="ai-grid">
              <!-- 左侧：AI 人设与店铺说明 -->
              <div class="ai-column-panel">
                <div class="panel-header">
                  <div class="panel-title">
                    <span class="title-text">店铺人设与特别说明</span>
                    <span class="title-desc">关键词未命中时，AI 会以此设定的语气、身份及规则向买家回复</span>
                  </div>
                  <el-button
                    type="primary"
                    size="small"
                    :loading="savingInstr"
                    :disabled="!instrDirty"
                    @click="saveInstructions"
                  >
                    保存人设说明
                  </el-button>
                </div>

                <!-- 快捷人设词签 -->
                <div class="prompt-chips-bar">
                  <span class="chips-title">快捷参考词：</span>
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
                    :rows="11"
                    :maxlength="MAX_INSTRUCTIONS"
                    show-word-limit
                    placeholder="用自然的语言告诉 AI 你的身份、店铺规矩和回复习惯，例如：&#10;· 我是个人自用转让，商品均实拍，谢绝议价&#10;· 回复亲切温暖，可以称呼“宝”&#10;· 统一发中通，每天下午 5 点前拍下当天发出&#10;· 电子卡券拍下自动发货，发出后不支持退换"
                  />
                </div>

                <div class="panel-foot-notice">
                  <el-icon><WarningFilled /></el-icon>
                  <span>安全底线提示：系统底价、防封号规则与违规拦截始终优先，人设中哪怕写了也不会突破。</span>
                </div>
              </div>

              <!-- 右侧：知识库资料文件 -->
              <div class="ai-column-panel">
                <div class="panel-header">
                  <div class="panel-title">
                    <span class="title-text">业务知识库与说明书</span>
                    <span class="title-desc">上传说明书、常见 FAQ、价格表等，AI 自动检索相关段落作答</span>
                  </div>

                  <div class="upload-action-wrap">
                    <el-upload :show-file-list="false" :accept="ACCEPT" :http-request="upload" multiple>
                      <el-button size="small" type="primary" plain :icon="Upload">上传新资料</el-button>
                    </el-upload>
                  </div>
                </div>

                <div class="scope-switch-bar">
                  <span class="scope-label">上传归属：</span>
                  <el-radio-group v-model="uploadScope" size="small">
                    <el-radio-button value="all">所有账号通用</el-radio-button>
                    <el-radio-button value="account">仅给当前账号</el-radio-button>
                  </el-radio-group>
                  <span class="scope-formats">支持 txt / md / csv / pdf / docx，单个 &lt; 50MB</span>
                </div>

                <div v-loading="docsLoading" class="docs-container">
                  <div v-if="!visibleDocs.length" class="empty-docs-box">
                    <el-icon class="empty-icon"><Document /></el-icon>
                    <div class="empty-title">暂未添加资料文件</div>
                    <div class="empty-desc">上传商品使用说明或常见问题解答，让 AI 问答更专业更具说服力</div>
                  </div>

                  <div v-else class="docs-list">
                    <div v-for="d in visibleDocs" :key="d.id" class="doc-card" :class="{ disabled: !d.enabled }">
                      <el-icon class="doc-file-icon"><Document /></el-icon>
                      <div class="doc-details">
                        <div class="doc-title-row">
                          <span class="doc-name" :title="d.name">{{ d.name }}</span>
                          <el-tag size="small" :type="d.account_id === null ? 'info' : 'primary'" effect="plain">
                            {{ d.account_id === null ? '所有账号通用' : '仅当前账号' }}
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
        <el-form-item label="回复内容" required>
          <el-input
            v-model="edit.form.reply"
            type="textarea"
            :rows="4"
            maxlength="1000"
            show-word-limit
            placeholder="买家触发该关键词后系统自动回复的内容"
          />
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

.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--xh-space-2);
}

.head-left h2 {
  font-size: var(--xh-fs-xl);
  font-weight: 700;
  color: var(--xh-text);
  margin: 0;
}

.head-subtitle {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
  margin-top: 2px;
  display: block;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
}

/* 账号回复策略概览条 */
.account-strip-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: 12px 16px;
  box-shadow: var(--xh-shadow-1);
}

.strip-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.strip-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--xh-fs-sm);
  font-weight: 600;
  color: var(--xh-text);
}

.title-icon {
  color: var(--xh-primary);
  font-size: 15px;
}

.strip-tip {
  font-size: var(--xh-fs-xs);
  font-weight: normal;
  color: var(--xh-muted);
  margin-left: 6px;
}

.nav-link {
  font-size: var(--xh-fs-xs);
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.empty-acc-banner {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
  padding: 8px 0;
}

.acc-capsule-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.acc-capsule {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 8px 14px;
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-sm);
  flex: 1 1 420px;
  max-width: 100%;
  transition: all 0.18s ease;
  cursor: pointer;
}

.acc-capsule:hover {
  border-color: var(--xh-primary-border);
}

.acc-capsule.active {
  border-color: var(--xh-primary);
  background: var(--xh-primary-soft);
}

.capsule-profile {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.capsule-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--xh-card);
  color: var(--xh-primary);
  border: 1px solid var(--xh-primary-border);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}

.capsule-info {
  min-width: 0;
}

.capsule-name {
  font-size: var(--xh-fs-sm);
  font-weight: 600;
  color: var(--xh-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 140px;
}

.capsule-status {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}

.status-warning {
  font-size: 11px;
  color: var(--xh-warning-text);
  background: #fef3c7;
  padding: 0 4px;
  border-radius: 3px;
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.capsule-controls {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-shrink: 0;
}

.ctrl-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.ctrl-label {
  font-size: 11px;
  color: var(--xh-muted);
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
}

.tab-count-badge :deep(.el-badge__content) {
  margin-left: 2px;
}

.tab-body {
  padding: 16px;
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

/* AI 设定网格 (2列并排) */
.tab-account-selector {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  padding: 8px 12px;
  background: var(--xh-fill);
  border-radius: var(--xh-radius-sm);
  border: 1px solid var(--xh-border);
}

.selector-label {
  font-size: var(--xh-fs-xs);
  font-weight: 600;
  color: var(--xh-text);
}

.ai-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

@media (max-width: 992px) {
  .ai-grid {
    grid-template-columns: 1fr;
  }
}

.ai-column-panel {
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-sm);
  padding: 14px;
  background: #fafbfc;
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
  font-weight: 600;
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
  background: #ffffff;
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

.scope-switch-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
  padding: 6px 10px;
  background: #ffffff;
  border: 1px solid var(--xh-border);
  border-radius: 4px;
}

.scope-label {
  font-size: 11px;
  color: var(--xh-muted);
}

.scope-formats {
  font-size: 11px;
  color: var(--xh-muted);
  margin-left: auto;
}

.docs-container {
  min-height: 240px;
  flex: 1;
}

.empty-docs-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 36px 16px;
  color: var(--xh-muted);
  background: #ffffff;
  border: 1px dashed var(--xh-border);
  border-radius: var(--xh-radius-sm);
  height: 100%;
}

.empty-icon {
  font-size: 36px;
  color: var(--xh-border-strong);
  margin-bottom: 8px;
}

.empty-title {
  font-size: var(--xh-fs-sm);
  font-weight: 600;
  color: var(--xh-text);
  margin-bottom: 4px;
}

.empty-desc {
  font-size: 11px;
  color: var(--xh-muted);
  text-align: center;
}

.docs-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.doc-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: #ffffff;
  border: 1px solid var(--xh-border);
  border-radius: 6px;
  transition: all 0.15s ease;
}

.doc-card.disabled {
  opacity: 0.6;
  background: var(--xh-fill);
}

.doc-file-icon {
  font-size: 20px;
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
  gap: 8px;
}

.doc-name {
  font-size: var(--xh-fs-sm);
  font-weight: 500;
  color: var(--xh-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-sub {
  font-size: 11px;
  color: var(--xh-muted);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.w-full {
  width: 100%;
}

.form-tip {
  font-size: 11px;
  color: var(--xh-muted);
  line-height: 1.5;
  margin-top: 4px;
}
</style>
