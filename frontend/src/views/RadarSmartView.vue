<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Bell,
  CaretRight,
  CopyDocument,
  Delete,
  Download,
  Edit,
  MoreFilled,
  Plus,
  Refresh,
  Search,
  TrendCharts,
  Upload,
  WarningFilled,
} from '@element-plus/icons-vue'
import {
  createTask,
  deleteTask,
  emptyRules,
  emptyTask,
  exportResults,
  generateTask,
  listResults,
  listTasks,
  markResult,
  priceHistory,
  runTask,
  taskMarket,
  updateTask,
  type MarketStats,
  type ResultOut,
  type TaskIn,
  type TaskOut,
  type UserMark,
} from '@/api/buyer'
import { errorMessage } from '@/api/http'
import EChart from '@/components/EChart.vue'
import ItemCard, { type CardItem, type CardMenuItem } from '@/components/ItemCard.vue'
import ItemDrawer, { type DrawerItem } from '@/components/ItemDrawer.vue'
import ListPager from '@/components/ListPager.vue'
import RadarNav from '@/components/RadarNav.vue'
import SmartTaskDialog from '@/components/SmartTaskDialog.vue'
import { useKeepScroll } from '@/composables/useKeepScroll'
import { askSellerOnGoofish, copyText, fmtMoney, fmtRelative, fmtTime, itemUrl, markMap, verdictMap } from '@/utils/format'

defineOptions({ name: 'RadarSmartView' })
useKeepScroll()

const route = useRoute()
const router = useRouter()

// ================================================================ 搜索任务（左栏）
const tasks = ref<TaskOut[]>([])
const tasksLoading = ref(false)
const busy = reactive<Record<string, boolean>>({})
let timer: number | undefined

async function loadTasks(silent = false) {
  if (!silent) tasksLoading.value = true
  try {
    const prevRunning = new Set(tasks.value.filter((t) => t.running).map((t) => t.id))
    tasks.value = await listTasks()
    // 有任务刚跑完：刷新结果
    const finished = [...prevRunning].some((id) => !tasks.value.find((t) => t.id === id)?.running)
    if (finished) load(page.value)
  } catch {
    /* 拦截器已提示 */
  } finally {
    tasksLoading.value = false
  }
}

// 后端时间不带时区后缀时按 UTC 解析
const parseUtc = (v: string) => new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(v) ? v : `${v}Z`).getTime()
const retryDue = (t: TaskOut) => !!t.retry_at && parseUtc(t.retry_at) <= Date.now()
function retryText(t: TaskOut) {
  const d = new Date(parseUtc(t.retry_at || ''))
  const p = (n: number) => String(n).padStart(2, '0')
  return retryDue(t) ? '正在重新尝试' : `${p(d.getHours())}:${p(d.getMinutes())} 自动重试`
}

function startTimer() {
  stopTimer()
  timer = window.setInterval(() => {
    // 搜索中，或退避重试已到点：刷新任务状态
    if (tasks.value.some((t) => t.running || retryDue(t))) loadTasks(true)
  }, 5000)
}
function stopTimer() {
  if (timer) window.clearInterval(timer)
  timer = undefined
}

const statusLabel: Record<string, { label: string; type: 'success' | 'danger' | 'warning' }> = {
  ok: { label: '成功', type: 'success' },
  error: { label: '失败', type: 'danger' },
  risk: { label: '风控', type: 'warning' },
}

function selectTask(id: number | undefined) {
  if (filters.task_id === id) return
  filters.task_id = id
  load(1)
}

const currentTask = computed(() => tasks.value.find((t) => t.id === filters.task_id) || null)
const totalRecommend = computed(() => tasks.value.reduce((n, t) => n + (t.result_counts.recommend || 0), 0))

function cronText(t: TaskOut) {
  if (!t.enabled) return '仅手动'
  const map: Record<string, string> = {
    '*/10 8-23 * * *': '每10分钟',
    '*/15 8-23 * * *': '每15分钟',
    '*/30 8-23 * * *': '每30分钟',
    '0 * * * *': '每小时',
    '0 */2 * * *': '每2小时',
    '0 9,21 * * *': '早晚各一次',
  }
  return map[t.cron] || t.cron
}

function toIn(t: TaskOut): TaskIn {
  const base = emptyTask()
  const out = { ...base } as Record<string, unknown>
  for (const k of Object.keys(base)) out[k] = (t as unknown as Record<string, unknown>)[k]
  const res = out as unknown as TaskIn
  res.rules = { ...emptyRules(), ...t.rules }
  return res
}

async function run(t: TaskOut) {
  busy[`run-${t.id}`] = true
  try {
    await runTask(t.id)
    ElMessage.success(`「${t.name}」开始搜索，结果会陆续出现在右侧`)
    selectTask(t.id)
    await loadTasks(true)
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[`run-${t.id}`] = false
  }
}

async function toggle(t: TaskOut, enabled: boolean) {
  busy[`en-${t.id}`] = true
  try {
    await updateTask(t.id, { ...toIn(t), enabled })
    ElMessage.success(enabled ? '已开启定时自动搜索' : '已关闭定时，仅手动搜索')
    await loadTasks(true)
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[`en-${t.id}`] = false
  }
}

async function remove(t: TaskOut) {
  await ElMessageBox.confirm(`删除「${t.name}」及其全部搜索结果？`, '删除智能搜索', { type: 'warning' })
  await deleteTask(t.id)
  ElMessage.success('已删除')
  if (filters.task_id === t.id) filters.task_id = undefined
  await loadTasks(true)
  load(1)
}

// ---------------------------------------------------------------- 新建 / 编辑
const dialog = reactive({
  open: false,
  task: null as TaskOut | null,
  preset: null as Partial<TaskIn> | null,
  nl: '' as string,
})
const quickKw = ref('')
const quickLoading = ref(false)

function openCreate(preset: Partial<TaskIn> | null = null, nl = '') {
  Object.assign(dialog, { open: true, task: null, preset, nl })
}
function openEdit(t: TaskOut) {
  Object.assign(dialog, { open: true, task: t, preset: null, nl: '' })
}

/** 像一句完整需求（带价格、条件、语气词）而不是几个关键词 */
function looksLikeSentence(text: string) {
  if (text.length >= 20) return true
  return text.length >= 8 && /[，。,；;！!？?]|想买|想要|求|预算|以内|以下|左右|不要|最好|电池|成色/.test(text)
}

async function quickCreate() {
  const text = quickKw.value.trim()
  if (!text) return openCreate()
  if (quickLoading.value) return

  quickLoading.value = true
  try {
    let taskData: TaskIn
    if (looksLikeSentence(text)) {
      try {
        const d = await generateTask(text)
        taskData = {
          ...emptyTask(),
          name: (d.name || text).slice(0, 32),
          keywords: d.keywords?.length ? d.keywords.slice(0, 8) : [text.slice(0, 32)],
          min_price: d.min_price ?? null,
          max_price: d.max_price ?? null,
          province: d.province ?? null,
          city: d.city ?? null,
          publish_days: d.publish_days ?? null,
          personal_only: !!d.personal_only,
          rules: {
            ...emptyRules(),
            include_all: d.rules?.include_all || [],
            exclude: d.rules?.exclude || [],
          },
          criteria: d.criteria || '',
          decision_mode: 'ai',
          enabled: true,
        }
      } catch {
        const keywords = text.split(/[,，、;；\s]+/).map((k) => k.trim()).filter(Boolean).slice(0, 8)
        taskData = {
          ...emptyTask(),
          name: text.slice(0, 32),
          keywords: keywords.length ? keywords : [text.slice(0, 32)],
          criteria: text,
          enabled: true,
        }
      }
    } else {
      const keywords = text.split(/[,，、;；]+/).map((k) => k.trim()).filter(Boolean).slice(0, 8)
      taskData = {
        ...emptyTask(),
        name: (keywords[0] || text).slice(0, 32),
        keywords: keywords.length ? keywords : [text.slice(0, 32)],
        enabled: true,
      }
    }

    const created = await createTask(taskData)
    quickKw.value = ''
    ElMessage.success(`「${created.name}」已创建并开始搜索`)
    await loadTasks(true)
    selectTask(created.id)
    await run(created)
  } catch (err) {
    ElMessage.error(errorMessage(err) || '创建搜索任务失败')
  } finally {
    quickLoading.value = false
  }
}

async function onSaved(t: TaskOut, created: boolean) {
  quickKw.value = ''
  await loadTasks(true)
  if (created) {
    selectTask(t.id)
    run(t)
  }
}

// ---------------------------------------------------------------- 行情统计
const market = reactive({ open: false, loading: false, task: null as TaskOut | null, data: null as MarketStats | null })
async function openMarket(t: TaskOut) {
  Object.assign(market, { open: true, loading: true, task: t, data: null })
  try {
    market.data = await taskMarket(t.id)
  } finally {
    market.loading = false
  }
}

function onTaskCommand(t: TaskOut, cmd: string) {
  if (cmd === 'market') openMarket(t)
  else if (cmd === 'delete') remove(t)
}

// ================================================================ 搜索结果（右栏）
const results = ref<ResultOut[]>([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(40)
const total = ref(0)
const exporting = ref(false)

const filters = reactive({
  task_id: (route.query.task_id ? Number(route.query.task_id) : undefined) as number | undefined,
  verdict: 'default',
  mark: '',
  sort: 'newest' as 'newest' | 'price_asc' | 'deal',
  q: '',
})

async function load(p = 1) {
  loading.value = true
  try {
    const res = await listResults({
      task_id: filters.task_id || undefined,
      verdict: filters.verdict,
      mark: filters.mark || undefined,
      sort: filters.sort,
      q: filters.q.trim() || undefined,
      limit: pageSize.value,
      offset: (p - 1) * pageSize.value,
    })
    const last = Math.max(1, Math.ceil(res.total / pageSize.value))
    if (!res.items.length && p > last) return await load(last)
    results.value = res.items
    total.value = res.total
    page.value = p
  } finally {
    loading.value = false
  }
}

const root = ref<HTMLElement>()
async function changePage() {
  await load(page.value)
  root.value?.scrollIntoView({ block: 'start', behavior: 'smooth' })
}

const taskName = computed(() => {
  const m = new Map(tasks.value.map((t) => [t.id, t.name]))
  return (id: number) => m.get(id) || `搜索 #${id}`
})

async function mark(r: ResultOut, m: UserMark) {
  const next: UserMark = r.mark === m ? 'none' : m
  try {
    await markResult(r.id, next)
    r.mark = next
    if (next === 'ignored' && !filters.mark) {
      results.value = results.value.filter((x) => x.id !== r.id)
      total.value = Math.max(0, total.value - 1)
    }
    ElMessage.success(next === 'none' ? '已取消标记' : `已标记为「${markMap[next]}」`)
  } catch {
    /* 拦截器已提示 */
  }
}

async function doExport() {
  exporting.value = true
  try {
    await exportResults(filters.task_id)
  } catch {
    /* 拦截器已提示 */
  } finally {
    exporting.value = false
  }
}

// 搜索结果 → 统一商品卡片
function toCard(r: ResultOut): CardItem {
  const v = verdictMap[r.verdict || (r.stage === 'filtered' ? 'filtered' : '')]
  return {
    title: r.item.title,
    image: r.item.image_url,
    price: r.item.price,
    origPrice: r.item.orig_price,
    // “样本不足”没有信息量，不展示
    priceNote: r.deal_label && r.deal_label !== '样本不足' ? r.deal_label : '',
    wantCnt: r.item.want_cnt,
    area: r.item.area,
    sellerNick: r.item.seller_nick,
    sellerTag: r.item.seller_zhima,
    textBadges: r.item.tags?.includes('包邮') ? ['包邮'] : [],
    badge: v
      ? {
          label: v.label + (r.confidence !== null && r.verdict ? ` ${Math.round(r.confidence * 100)}%` : ''),
          type: v.type === 'primary' ? 'info' : v.type,
        }
      : null,
    note: r.reason || r.filter_reasons.join('；'),
    subline: (filters.task_id ? '' : `${taskName.value(r.task_id)} · `) + fmtRelative(r.created_at),
  }
}

// ---------------------------------------------------------------- 对比：同款多个候选并排看
const COMPARE_MAX = 4
const compare = ref<ResultOut[]>([])
const compareOpen = ref(false)
const inCompare = (r: ResultOut) => compare.value.some((x) => x.id === r.id)
function toggleCompare(r: ResultOut) {
  if (inCompare(r)) compare.value = compare.value.filter((x) => x.id !== r.id)
  else if (compare.value.length >= COMPARE_MAX) ElMessage.warning(`最多同时对比 ${COMPARE_MAX} 件`)
  else compare.value = [...compare.value, r]
}
const compareRows: { label: string; value: (r: ResultOut) => string }[] = [
  { label: '价格', value: (r) => fmtMoney(r.item.price) },
  { label: '性价比', value: (r) => (r.deal_label && r.deal_label !== '样本不足' ? r.deal_label : '—') },
  {
    label: 'AI 判定',
    value: (r) =>
      r.verdict
        ? `${verdictMap[r.verdict]?.label || r.verdict}${r.confidence !== null ? ` · ${Math.round(r.confidence * 100)}%` : ''}`
        : '已筛除',
  },
  { label: '理由', value: (r) => r.reason || r.filter_reasons.join('；') || '—' },
  { label: '风险', value: (r) => r.risk_tags.join('、') || '—' },
  { label: '需确认', value: (r) => r.need_confirm.join('；') || '—' },
  { label: '地区', value: (r) => r.item.area || '—' },
  { label: '卖家', value: (r) => [r.item.seller_nick, r.item.seller_zhima].filter(Boolean).join(' · ') || '—' },
  { label: '想要', value: (r) => (r.item.want_cnt ? `${r.item.want_cnt} 人` : '—') },
  { label: '发现时间', value: (r) => fmtRelative(r.created_at) },
]

function cardMenu(r: ResultOut): CardMenuItem[] {
  return [
    { key: 'compare', label: inCompare(r) ? '移出对比' : '加入对比' },
    { key: 'seen', label: r.mark === 'seen' ? '取消「已看」' : '标记为已看', divided: true },
    { key: 'bought', label: r.mark === 'bought' ? '取消「已买」' : '标记为已买' },
    { key: 'ignored', label: '不感兴趣' },
    { key: 'history', label: '价格走势', divided: true },
    { key: 'watch', label: '加入价格监控' },
    { key: 'resell', label: '转手发品' },
    { key: 'open', label: '去闲鱼查看', divided: true },
  ]
}

function onCardAction(r: ResultOut, key: string) {
  if (key === 'compare') toggleCompare(r)
  else if (key === 'seen' || key === 'bought' || key === 'ignored') mark(r, key)
  else if (key === 'history') openHistory(r)
  else if (key === 'watch') watchPrice(r)
  else if (key === 'resell') quickResell(r)
  else if (key === 'open') window.open(itemLink(r), '_blank', 'noopener')
}

function itemLink(r: ResultOut) {
  return r.item.link || itemUrl(r.item_id)
}

const history = reactive({ open: false, loading: false, title: '', points: [] as { price: number; seen_at: string }[] })
async function openHistory(r: ResultOut) {
  Object.assign(history, { open: true, loading: true, title: r.item.title, points: [] })
  try {
    history.points = await priceHistory(r.item_id)
  } finally {
    history.loading = false
  }
}
const historyOption = computed(() => ({
  grid: { left: 48, right: 16, top: 24, bottom: 32 },
  tooltip: { trigger: 'axis', valueFormatter: (v: number) => `¥${v}` },
  xAxis: { type: 'category', data: history.points.map((p) => fmtTime(p.seen_at)), axisLabel: { hideOverlap: true } },
  yAxis: { type: 'value', scale: true, axisLabel: { formatter: '¥{value}' } },
  series: [
    {
      type: 'line',
      step: 'end',
      data: history.points.map((p) => p.price),
      itemStyle: { color: '#1e9e6a' },
      areaStyle: { color: 'rgba(30,158,106,0.08)' },
    },
  ],
}))

// 详情抽屉：图片、描述来自已存的商品库，不额外请求闲鱼
const detail = reactive({ open: false, result: null as ResultOut | null })
function openDetail(r: ResultOut) {
  Object.assign(detail, { open: true, result: r })
}
const drawerBase = computed<DrawerItem | null>(() => {
  const r = detail.result
  if (!r) return null
  return {
    title: r.item.title,
    image: r.item.image_url,
    images: r.item.images,
    price: r.item.price,
    origPrice: r.item.orig_price,
    wantCnt: r.item.want_cnt,
    browseCnt: r.item.browse_cnt,
    area: r.item.area,
    sellerNick: r.item.seller_nick,
    desc: r.item.desc,
    link: itemLink(r),
  }
})
const markOptions: { key: UserMark; label: string }[] = [
  { key: 'favorite', label: '收藏' },
  { key: 'seen', label: '已看' },
  { key: 'bought', label: '已买' },
  { key: 'ignored', label: '不感兴趣' },
]

function quickResell(r: ResultOut) {
  const p = r.item.price || 0
  const suggestedPrice = Math.round(p * 1.15) || p
  router.push({
    path: '/goods/publish',
    query: { from: 'resell', title: r.item.title, price: suggestedPrice || undefined, hint: `原低价捡漏入手，原价 ${p}，成色完好，转手诚出` },
  })
}

function watchPrice(r: ResultOut) {
  router.push({ path: '/radar/watch', query: { add: r.item_id, title: r.item.title, price: r.item.price ?? undefined } })
}

// ================================================================ 生命周期（配合 KeepAlive）
let lastQueryTaskId: number | undefined = filters.task_id

onMounted(() => {
  loadTasks()
  load()
  startTimer()
})

onActivated(() => {
  const q = route.query.task_id ? Number(route.query.task_id) : undefined
  if (q !== undefined && q !== lastQueryTaskId) {
    lastQueryTaskId = q
    selectTask(q)
  }
  loadTasks(true)
  startTimer()
})

onDeactivated(stopTimer)
onBeforeUnmount(stopTimer)
</script>

<template>
  <div ref="root" class="page">
    <RadarNav current="smart">
      <template #actions>
        <el-button :icon="Refresh" :loading="loading" @click="loadTasks(true); load(page)">刷新</el-button>
        <el-button :icon="Download" :loading="exporting" @click="doExport">导出</el-button>
      </template>
    </RadarNav>

    <!-- 新建：一个入口。输入关键词回车直接创建并搜索，无需弹窗二次确认；留空点击可打开完整配置弹窗 -->
    <div class="quick">
      <el-input
        v-model="quickKw"
        size="large"
        clearable
        :prefix-icon="Search"
        placeholder="想买什么？输入关键词，或直接说需求：2000 以内的 iPhone 13，电池 85 以上，不要维修过的"
        :disabled="quickLoading"
        @keyup.enter="quickCreate"
      />
      <el-button
        size="large"
        type="primary"
        :icon="quickKw.trim() ? Search : Plus"
        :loading="quickLoading"
        @click="quickCreate"
      >
        {{ quickKw.trim() ? '直接搜索' : '新建智能搜索' }}
      </el-button>
    </div>

    <div class="layout">
      <!-- 左栏：我的搜索 -->
      <aside v-loading="tasksLoading" class="tasks">
        <div class="tasks-head">
          <span>我的搜索</span>
          <span class="muted small">{{ tasks.length }}</span>
        </div>
        <button type="button" class="task all" :class="{ active: !filters.task_id }" @click="selectTask(undefined)">
          <span class="t-name">全部结果</span>
          <span v-if="totalRecommend" class="t-count" title="推荐数量">{{ totalRecommend }}</span>
        </button>
        <p v-if="!tasksLoading && !tasks.length" class="tasks-empty">
          暂无智能搜索任务
        </p>
        <div
          v-for="t in tasks"
          :key="t.id"
          class="task"
          :class="{ active: filters.task_id === t.id }"
          role="button"
          tabindex="0"
          @click="selectTask(t.id)"
          @keyup.enter="selectTask(t.id)"
        >
          <div class="t-row">
            <span class="dot" :class="t.running ? 'running' : t.retry_at ? 'wait' : t.paused_reason || (t.last_status && t.last_status !== 'ok') ? 'bad' : t.enabled ? 'on' : 'off'" />
            <span class="t-name ellipsis">{{ t.name }}</span>
            <span v-if="t.running" class="t-state">搜索中</span>
            <span v-else-if="t.result_counts.recommend" class="t-count" title="推荐数量">{{ t.result_counts.recommend }}</span>
          </div>
          <div class="t-meta ellipsis">
            {{ cronText(t) }}<template v-if="t.last_run_at"> · {{ statusLabel[t.last_status || '']?.label && t.last_status !== 'ok' ? statusLabel[t.last_status || ''].label + ' · ' : '' }}{{ fmtRelative(t.last_run_at) }}</template>
          </div>
          <div v-if="t.paused_reason" class="t-paused" :title="`已暂停：${t.paused_reason}`">已暂停：{{ t.paused_reason }}</div>
          <div v-else-if="t.retry_at && !t.running" class="t-wait" :title="t.last_error || ''">闲鱼临时限制，{{ retryText(t) }}</div>
          <div class="t-ops" @click.stop>
            <el-button size="small" link type="primary" :icon="CaretRight" :loading="busy[`run-${t.id}`]" :disabled="t.running" @click="run(t)">搜索</el-button>
            <el-button size="small" link :icon="Edit" @click="openEdit(t)">编辑</el-button>
            <el-switch
              :model-value="t.enabled"
              :loading="busy[`en-${t.id}`]"
              size="small"
              inline-prompt
              active-text="定时"
              inactive-text="手动"
              @change="(v: string | number | boolean) => toggle(t, !!v)"
            />
            <el-dropdown trigger="click" @command="(c: string) => onTaskCommand(t, c)">
              <el-button size="small" link :icon="MoreFilled" aria-label="更多" />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="market" :icon="TrendCharts">行情统计</el-dropdown-item>
                  <el-dropdown-item command="delete" :icon="Delete" divided><span class="danger">删除</span></el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
      </aside>

      <!-- 右栏：结果 -->
      <section class="results">
        <div class="filter-bar">
          <div class="scope">
            <b class="ellipsis">{{ currentTask ? currentTask.name : '全部结果' }}</b>
            <span class="muted small">{{ total }} 件</span>
          </div>
          <el-select v-model="filters.verdict" class="f-sel" @change="load()">
            <el-option value="default" label="推荐 + 需核验" />
            <el-option value="recommend" label="仅推荐" />
            <el-option value="conditional" label="仅需核验" />
            <el-option value="reject" label="不推荐" />
            <el-option value="filtered" label="已筛除" />
            <el-option value="all" label="全部" />
          </el-select>
          <el-select v-model="filters.mark" clearable placeholder="全部标记" class="f-sel" @change="load()">
            <el-option v-for="(label, k) in markMap" :key="k" :value="k" :label="label" />
          </el-select>
          <el-select v-model="filters.sort" class="f-sel" @change="load()">
            <el-option value="newest" label="最新发现" />
            <el-option value="deal" label="性价比最高" />
            <el-option value="price_asc" label="价格从低到高" />
          </el-select>
          <el-input v-model="filters.q" placeholder="标题关键词" clearable class="f-q" :prefix-icon="Search" @keyup.enter="load()" @clear="load()" />
        </div>

        <div v-loading="loading" class="grid">
          <div v-if="!loading && !results.length" class="empty-state-wrap">
            <el-empty
              class="empty"
              :image-size="80"
              :description="tasks.length ? (currentTask?.running ? '正在搜索中…' : '暂无符合条件的商品') : '暂无搜索结果'"
            >
              <template #description>
                <div class="empty-desc-box">
                  <p class="empty-main-text">{{ tasks.length ? (currentTask?.running ? '正在搜索中，稍候出结果…' : '暂无符合筛选条件的商品') : '输入关键词，开始你的第一个智能搜索' }}</p>
                  <p v-if="currentTask?.paused_reason" class="empty-paused-hint">
                    <el-icon><WarningFilled /></el-icon>
                    <span>当前任务已暂停：{{ currentTask.paused_reason }}</span>
                  </p>
                  <p v-else-if="currentTask?.retry_at && !currentTask.running" class="empty-wait-hint">
                    闲鱼临时限制了搜索，系统会在后台等待，{{ retryText(currentTask) }}
                  </p>
                </div>
              </template>
              <div class="empty-actions-row">
                <el-button v-if="currentTask && !currentTask.running" type="primary" :icon="CaretRight" @click="run(currentTask)">立即搜索</el-button>
                <el-button v-if="filters.verdict !== 'all' || filters.q" @click="filters.verdict = 'all'; filters.q = ''; load()">查看全部状态</el-button>
                <el-button @click="router.push('/radar/search')">先去实时搜货看看</el-button>
              </div>
            </el-empty>
          </div>
          <ItemCard
            v-for="r in results"
            :key="r.id"
            :item="toCard(r)"
            :starred="r.mark === 'favorite'"
            :menu="cardMenu(r)"
            @open="openDetail(r)"
            @star="mark(r, 'favorite')"
            @action="(k: string) => onCardAction(r, k)"
          />
        </div>

        <ListPager
          v-if="total > 0"
          v-model:page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 40, 80, 120]"
          :disabled="loading"
          @change="changePage"
        />
      </section>
    </div>

    <!-- 对比栏 -->
    <div v-if="compare.length" class="compare-bar">
      <span>已选 <b>{{ compare.length }}</b> / {{ COMPARE_MAX }} 件</span>
      <el-image v-for="r in compare" :key="r.id" :src="r.item.image_url" fit="cover" class="compare-thumb" referrerpolicy="no-referrer" />
      <el-button type="primary" size="small" :disabled="compare.length < 2" @click="compareOpen = true">开始对比</el-button>
      <el-button size="small" link @click="compare = []">清空</el-button>
    </div>

    <el-dialog v-model="compareOpen" title="对比" width="min(1080px, 96vw)" top="5vh">
      <div class="compare-table" :style="{ gridTemplateColumns: `88px repeat(${compare.length}, minmax(180px, 1fr))` }">
        <div class="ct-label" />
        <div v-for="r in compare" :key="`h${r.id}`" class="ct-head">
          <el-image :src="r.item.image_url" fit="cover" class="ct-img" referrerpolicy="no-referrer" />
          <a :href="itemLink(r)" target="_blank" rel="noopener" class="ct-title">{{ r.item.title }}</a>
          <div class="ct-ops">
            <el-button size="small" link type="primary" @click="compareOpen = false; openDetail(r)">详情</el-button>
            <el-button size="small" link @click="toggleCompare(r)">移除</el-button>
          </div>
        </div>
        <template v-for="row in compareRows" :key="row.label">
          <div class="ct-label">{{ row.label }}</div>
          <div v-for="r in compare" :key="`${row.label}${r.id}`" class="ct-cell" :class="{ price: row.label === '价格' }">{{ row.value(r) }}</div>
        </template>
      </div>
    </el-dialog>

    <SmartTaskDialog v-model="dialog.open" :task="dialog.task" :preset="dialog.preset" :nl="dialog.nl" @saved="onSaved" />

    <ItemDrawer v-model="detail.open" :item-id="detail.result?.item_id || ''" :base="drawerBase" :task-id="detail.result?.task_id">
      <template #verdict>
        <section v-if="detail.result" class="verdict">
          <div class="v-head">
            <span class="v-title">AI 判定</span>
            <el-tag v-if="detail.result.verdict" :type="verdictMap[detail.result.verdict]?.type" size="small">
              {{ verdictMap[detail.result.verdict]?.label }}
              <template v-if="detail.result.confidence !== null"> · 置信度 {{ Math.round(detail.result.confidence * 100) }}%</template>
            </el-tag>
            <el-tag v-else size="small" type="info">已筛除</el-tag>
          </div>
          <p v-if="detail.result.reason || detail.result.filter_reasons.length" class="v-reason">
            {{ detail.result.reason || detail.result.filter_reasons.join('；') }}
          </p>
          <div v-if="detail.result.risk_tags.length" class="v-tags">
            <el-tag v-for="tg in detail.result.risk_tags" :key="tg" size="small" type="danger">{{ tg }}</el-tag>
          </div>
          <div v-if="detail.result.need_confirm.length" class="v-block">
            <div class="v-label">需要向卖家确认</div>
            <ul>
              <li v-for="c in detail.result.need_confirm" :key="c">{{ c }}</li>
            </ul>
          </div>
          <div v-if="detail.result.questions.length" class="v-block">
            <div class="v-label">
              可以这样问卖家
              <span>
                <el-button link size="small" :icon="CopyDocument" @click="copyText(detail.result.questions.join('\n'))">复制全部</el-button>
                <el-button link size="small" type="primary" @click="askSellerOnGoofish(detail.result.questions, itemLink(detail.result))">去闲鱼问卖家</el-button>
              </span>
            </div>
            <button v-for="q in detail.result.questions" :key="q" type="button" class="v-q" title="点击复制" @click="copyText(q)">{{ q }}</button>
          </div>
          <div class="v-marks">
            <span class="v-label">标记</span>
            <el-button
              v-for="m in markOptions"
              :key="m.key"
              size="small"
              :type="detail.result.mark === m.key ? 'primary' : 'default'"
              :plain="detail.result.mark === m.key"
              @click="mark(detail.result, m.key)"
            >
              {{ m.label }}
            </el-button>
          </div>
        </section>
      </template>
      <template #actions>
        <el-button v-if="detail.result" :icon="TrendCharts" @click="openHistory(detail.result)">价格走势</el-button>
        <el-button v-if="detail.result" :icon="Bell" @click="watchPrice(detail.result)">加入价格监控</el-button>
        <el-button v-if="detail.result" :icon="Upload" @click="quickResell(detail.result)">转手发品</el-button>
      </template>
    </ItemDrawer>

    <el-dialog v-model="history.open" title="价格走势" width="640px">
      <div class="muted small ellipsis">{{ history.title }}</div>
      <div v-loading="history.loading">
        <el-empty v-if="!history.loading && history.points.length < 2" :description="history.points.length ? `仅有一次记录：¥${history.points[0]?.price}` : '暂无价格记录'" :image-size="60" />
        <EChart v-else-if="history.points.length" :option="historyOption" height="280px" />
      </div>
    </el-dialog>

    <el-dialog v-model="market.open" :title="`行情统计 · ${market.task?.name || ''}`" width="480px">
      <div v-loading="market.loading">
        <el-empty v-if="market.data && !market.data.count" description="样本不足" :image-size="60" />
        <el-descriptions v-else-if="market.data" :column="2" border size="small">
          <el-descriptions-item label="样本数">{{ market.data.count }}</el-descriptions-item>
          <el-descriptions-item label="均价">{{ fmtMoney(market.data.mean) }}</el-descriptions-item>
          <el-descriptions-item label="最低">{{ fmtMoney(market.data.min) }}</el-descriptions-item>
          <el-descriptions-item label="最高">{{ fmtMoney(market.data.max) }}</el-descriptions-item>
          <el-descriptions-item label="P25">{{ fmtMoney(market.data.p25) }}</el-descriptions-item>
          <el-descriptions-item label="中位数">{{ fmtMoney(market.data.median) }}</el-descriptions-item>
          <el-descriptions-item label="P75">{{ fmtMoney(market.data.p75) }}</el-descriptions-item>
        </el-descriptions>
        <div class="form-tip">统计范围：这个搜索抓到的全部商品（已剔除离群值）。上次搜索：{{ fmtTime(market.task?.last_run_at) }}</div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.quick {
  display: flex;
  gap: var(--xh-space-2);
}
.quick .el-button {
  flex-shrink: 0;
}
.layout {
  display: grid;
  grid-template-columns: 264px minmax(0, 1fr);
  gap: var(--xh-space-4);
  align-items: start;
}

/* 左栏：我的搜索 */
.tasks {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-2);
  max-height: calc(100vh - 140px);
  min-height: 80px;
  overflow-y: auto;
  padding: 2px;
}
.tasks-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 0 var(--xh-space-1);
  font-weight: 600;
  color: var(--xh-text);
}
.tasks-empty {
  margin: 0;
  padding: var(--xh-space-3);
  border: 1px dashed var(--xh-border-strong);
  border-radius: var(--xh-radius-md);
  font-size: var(--xh-fs-xs);
  line-height: 1.6;
  color: var(--xh-muted);
}
.task {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-1);
  padding: 10px var(--xh-space-3);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  background: var(--xh-card);
  text-align: left;
  font: inherit;
  cursor: pointer;
  outline: none;
  transition: border-color 0.15s;
}
.task:hover {
  border-color: var(--xh-primary-border);
}
.task.active {
  border-color: var(--xh-primary);
  background: var(--xh-primary-soft);
}
.task:focus-visible {
  outline: 2px solid var(--xh-primary);
  outline-offset: 1px;
}
.task.all {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}
.t-row {
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
}
.t-name {
  flex: 1;
  min-width: 0;
  font-weight: 600;
  color: var(--xh-text);
}
.dot {
  width: 8px;
  height: 8px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--xh-disabled);
}
.dot.on {
  background: var(--xh-success);
}
.dot.running {
  background: var(--xh-primary);
  box-shadow: 0 0 0 3px var(--xh-primary-soft);
}
.dot.bad {
  background: var(--xh-danger);
}
.dot.wait {
  background: var(--xh-warning);
}
.t-state {
  font-size: var(--xh-fs-xs);
  color: var(--xh-primary);
}
.t-count {
  min-width: 20px;
  padding: 0 6px;
  border-radius: var(--xh-radius-pill);
  background: var(--xh-primary);
  color: #fff;
  font-size: var(--xh-fs-xs);
  line-height: 18px;
  text-align: center;
}
.t-meta {
  padding-left: 16px;
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}
.t-paused {
  padding-left: 16px;
  font-size: var(--xh-fs-xs);
  color: var(--xh-danger);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.t-wait {
  padding-left: 16px;
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.t-ops {
  display: flex;
  align-items: center;
  gap: var(--xh-space-1);
  padding-left: 12px;
}
.t-ops .el-button + .el-button {
  margin-left: 0;
}
.t-ops .el-switch {
  margin-left: auto;
}
.danger {
  color: var(--xh-danger);
}

/* 右栏：结果 */
.results {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-3);
  min-width: 0;
}
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--xh-space-2);
  padding: 10px var(--xh-space-3);
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
}
.scope {
  display: flex;
  align-items: baseline;
  gap: var(--xh-space-2);
  min-width: 0;
  margin-right: auto;
}
.f-sel {
  width: 136px;
}
.f-q {
  width: 180px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: var(--xh-space-4);
  min-height: 160px;
}
.empty-state-wrap {
  grid-column: 1 / -1;
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-lg);
  padding: var(--xh-space-8) var(--xh-space-4);
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 360px;
}
.empty-desc-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--xh-space-1);
}
.empty-main-text {
  margin: 0;
  font-size: var(--xh-fs-base);
  color: var(--xh-text-2);
}
.empty-wait-hint {
  margin: var(--xh-space-2) 0 0;
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}
.empty-paused-hint {
  margin: var(--xh-space-2) 0 0;
  padding: var(--xh-space-2) var(--xh-space-3);
  background: var(--xh-danger-soft);
  color: var(--xh-danger);
  border-radius: var(--xh-radius-sm);
  font-size: var(--xh-fs-xs);
  max-width: 520px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.empty-actions-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: var(--xh-space-2);
  margin-top: var(--xh-space-2);
}
.empty {
  grid-column: 1 / -1;
}

/* 抽屉：AI 判定 */
.verdict {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-2);
  padding: var(--xh-space-3);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
}
.v-head {
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
}
.v-title {
  font-weight: 600;
  color: var(--xh-text);
}
.v-reason {
  margin: 0;
  font-size: var(--xh-fs-sm);
  line-height: 1.6;
  color: var(--xh-text-2);
}
.v-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--xh-space-1);
}
.v-block ul {
  margin: var(--xh-space-1) 0 0;
  padding-left: 18px;
  font-size: var(--xh-fs-sm);
  line-height: 1.7;
  color: var(--xh-text-2);
}
.v-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--xh-fs-xs);
  font-weight: 600;
  color: var(--xh-muted);
}
.v-q {
  display: block;
  width: 100%;
  margin-top: var(--xh-space-1);
  padding: 6px var(--xh-space-2);
  border: none;
  border-radius: var(--xh-radius-sm);
  background: var(--xh-primary-soft);
  color: var(--xh-text);
  font-size: var(--xh-fs-sm);
  text-align: left;
  cursor: pointer;
}
.v-q:hover {
  background: var(--el-color-primary-light-8);
}
.v-marks {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--xh-space-2);
  padding-top: var(--xh-space-2);
  border-top: 1px dashed var(--xh-border);
}
.v-marks .el-button + .el-button {
  margin-left: 0;
}

/* 对比 */
.compare-bar {
  position: sticky;
  bottom: var(--xh-space-3);
  z-index: 10;
  align-self: center;
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
  padding: var(--xh-space-2) var(--xh-space-4);
  background: var(--xh-card);
  border: 1px solid var(--xh-primary-border);
  border-radius: var(--xh-radius-pill);
  box-shadow: var(--xh-shadow-2);
  font-size: var(--xh-fs-sm);
}
.compare-thumb {
  width: 28px;
  height: 28px;
  border-radius: var(--xh-radius-sm);
}
.compare-table {
  display: grid;
  border-top: 1px solid var(--xh-border);
  font-size: var(--xh-fs-sm);
}
.compare-table > div {
  padding: var(--xh-space-2);
  border-bottom: 1px solid var(--xh-border);
}
.ct-label {
  color: var(--xh-muted);
  font-size: var(--xh-fs-xs);
}
.ct-head {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ct-img {
  width: 120px;
  height: 120px;
  border-radius: var(--xh-radius-sm);
  background: var(--xh-fill);
}
.ct-title {
  color: var(--xh-text);
  font-weight: 500;
  line-height: 1.4;
  text-decoration: none;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.ct-title:hover {
  color: var(--xh-primary);
}
.ct-ops .el-button + .el-button {
  margin-left: var(--xh-space-2);
}
.ct-cell {
  line-height: 1.6;
  color: var(--xh-text-2);
}
.ct-cell.price {
  color: var(--xh-price);
  font-weight: 700;
  font-size: var(--xh-fs-lg);
}
@media (max-width: 900px) {
  .layout {
    grid-template-columns: 1fr;
  }
  .tasks {
    position: static;
    max-height: none;
  }
}
@media (max-width: 768px) {
  .quick {
    flex-wrap: wrap;
  }
  .f-sel,
  .f-q {
    width: calc(50% - 4px);
  }
  .grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--xh-space-2);
  }
}
</style>
