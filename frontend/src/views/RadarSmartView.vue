<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Bell,
  CaretRight,
  CopyDocument,
  DataAnalysis,
  Delete,
  Download,
  Edit,
  Link,
  MagicStick,
  MoreFilled,
  Plus,
  Refresh,
  Search,
  TrendCharts,
  Upload,
} from '@element-plus/icons-vue'
import {
  deleteTask,
  emptyRules,
  emptyTask,
  exportResults,
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
import EChart from '@/components/EChart.vue'
import ItemAnalysisPanel from '@/components/ItemAnalysisPanel.vue'
import ListPager from '@/components/ListPager.vue'
import RadarNav from '@/components/RadarNav.vue'
import SmartTaskDialog from '@/components/SmartTaskDialog.vue'
import { useKeepScroll } from '@/composables/useKeepScroll'
import { copyText, fmtMoney, fmtRelative, fmtTime, itemUrl, markMap, verdictMap } from '@/utils/format'

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

function startTimer() {
  stopTimer()
  timer = window.setInterval(() => {
    if (tasks.value.some((t) => t.running)) loadTasks(true)
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
const dialog = reactive({ open: false, task: null as TaskOut | null, preset: null as Partial<TaskIn> | null })
const quickKw = ref('')

function openCreate(preset: Partial<TaskIn> | null = null) {
  Object.assign(dialog, { open: true, task: null, preset })
}
function openEdit(t: TaskOut) {
  Object.assign(dialog, { open: true, task: t, preset: null })
}
function quickCreate() {
  const kw = quickKw.value.trim()
  if (!kw) return openCreate()
  openCreate({ name: kw.slice(0, 32), keywords: kw.split(/[\s,，]+/).filter(Boolean).slice(0, 8) })
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

function dealType(label: string): 'success' | 'warning' | 'danger' | 'info' {
  if (label === '高性价比') return 'success'
  if (label === '值得关注') return 'warning'
  if (label === '价格偏高') return 'danger'
  return 'info'
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

const analysis = reactive({ open: false, result: null as ResultOut | null, tab: 'item' as 'item' | 'seller' | 'ai' })
function openAnalysis(r: ResultOut, tab: 'item' | 'seller' | 'ai' = 'item') {
  Object.assign(analysis, { open: true, result: r, tab })
}

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
        <el-button :icon="Download" :loading="exporting" @click="doExport">导出 CSV</el-button>
      </template>
    </RadarNav>

    <!-- 快速新建：输入关键词回车 -->
    <div class="quick">
      <el-input
        v-model="quickKw"
        size="large"
        clearable
        placeholder="输入想买的东西，例如：iPhone 13 128G、宜家书桌……回车新建智能搜索"
        :prefix-icon="Search"
        class="quick-input"
        @keyup.enter="quickCreate"
      />
      <el-button size="large" type="primary" :icon="Plus" @click="quickCreate">新建智能搜索</el-button>
      <el-button size="large" :icon="MagicStick" @click="openCreate()">一句话生成</el-button>
    </div>

    <div class="layout">
      <!-- 左栏：搜索任务 -->
      <aside v-loading="tasksLoading" class="tasks">
        <div class="tasks-head">
          <span>我的搜索</span>
          <span class="muted small">{{ tasks.length }} 个</span>
        </div>

        <button type="button" class="task all" :class="{ active: !filters.task_id }" @click="selectTask(undefined)">
          <span class="t-name">全部结果</span>
          <span v-if="totalRecommend" class="t-badge">{{ totalRecommend }}</span>
        </button>

        <div v-if="!tasksLoading && !tasks.length" class="tasks-empty muted small">
          还没有智能搜索。在上方输入关键词回车，系统会定时搜索闲鱼并用 AI 挑出好货。
        </div>

        <div
          v-for="t in tasks"
          :key="t.id"
          class="task"
          :class="{ active: filters.task_id === t.id, disabled: !t.enabled }"
          role="button"
          tabindex="0"
          @click="selectTask(t.id)"
          @keyup.enter="selectTask(t.id)"
        >
          <div class="t-row">
            <span class="t-name ellipsis">{{ t.name }}</span>
            <el-tag v-if="t.running" size="small" type="primary" effect="dark">搜索中</el-tag>
            <span v-else-if="t.result_counts.recommend" class="t-badge">{{ t.result_counts.recommend }}</span>
          </div>
          <div class="t-kw ellipsis small">{{ t.keywords.join(' · ') }}</div>
          <div class="t-meta small">
            <span>{{ cronText(t) }}</span>
            <template v-if="t.last_run_at">
              <span>·</span>
              <el-tag v-if="t.last_status && t.last_status !== 'ok'" size="small" :type="statusLabel[t.last_status]?.type || 'info'" effect="plain">
                {{ statusLabel[t.last_status]?.label || t.last_status }}
              </el-tag>
              <span>{{ fmtRelative(t.last_run_at) }}</span>
            </template>
          </div>
          <div v-if="t.paused_reason" class="t-paused small">已自动暂停：{{ t.paused_reason }}</div>
          <div class="t-ops" @click.stop>
            <el-button size="small" type="primary" link :icon="CaretRight" :loading="busy[`run-${t.id}`]" :disabled="t.running" @click="run(t)">立即搜索</el-button>
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
              <el-button size="small" link :icon="MoreFilled" />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="market" :icon="TrendCharts">行情统计</el-dropdown-item>
                  <el-dropdown-item command="delete" :icon="Delete" divided><span class="err">删除</span></el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
      </aside>

      <!-- 右栏：结果 -->
      <section class="results">
        <el-card shadow="never" class="filters">
          <div class="toolbar">
            <div class="scope">
              <b>{{ currentTask ? currentTask.name : '全部结果' }}</b>
              <span class="muted small">共 {{ total }} 件</span>
            </div>
            <el-select v-model="filters.verdict" class="f-sel" @change="load()">
              <el-option value="default" label="优质精选（推荐 + 需核验）" />
              <el-option value="recommend" label="💎 仅超值捡漏" />
              <el-option value="conditional" label="⚠️ 仅需核验" />
              <el-option value="reject" label="🚫 不推荐" />
              <el-option value="filtered" label="已筛除" />
              <el-option value="all" label="全部状态" />
            </el-select>
            <el-select v-model="filters.mark" clearable placeholder="全部标记" class="f-sel" @change="load()">
              <el-option v-for="(label, k) in markMap" :key="k" :value="k" :label="label" />
            </el-select>
            <el-select v-model="filters.sort" class="f-sel" @change="load()">
              <el-option value="deal" label="性价比最高" />
              <el-option value="newest" label="最新发现" />
              <el-option value="price_asc" label="价格从低到高" />
            </el-select>
            <el-input v-model="filters.q" placeholder="标题关键词" clearable class="f-q" :prefix-icon="Search" @keyup.enter="load()" @clear="load()" />
          </div>
        </el-card>

        <div v-loading="loading" class="grid">
          <div v-if="!loading && !results.length" class="empty-state-box">
            <el-empty :description="tasks.length ? (currentTask?.running ? '正在搜索，结果马上就来…' : '暂无符合条件的好货') : '输入关键词，开始你的第一个智能搜索'">
              <div class="empty-actions">
                <el-button v-if="currentTask && !currentTask.running" type="primary" :icon="CaretRight" @click="run(currentTask)">立即搜索</el-button>
                <el-button v-else-if="!tasks.length" type="primary" :icon="Plus" @click="openCreate()">新建智能搜索</el-button>
                <el-button :icon="Search" @click="router.push('/radar/search')">先去实时搜货看看</el-button>
              </div>
            </el-empty>
          </div>
          <el-card v-for="r in results" :key="r.id" shadow="hover" class="card" :body-style="{ padding: '0' }">
            <div class="img-wrap">
              <el-image :src="r.item.image_url" fit="cover" lazy class="img" referrerpolicy="no-referrer">
                <template #error><div class="img-err">无图</div></template>
              </el-image>
              <el-tag v-if="r.verdict || r.stage === 'filtered'" class="verdict" :type="verdictMap[r.verdict || 'filtered']?.type" effect="dark" size="small">
                {{ verdictMap[r.verdict || 'filtered']?.label }}
                <template v-if="r.confidence !== null"> · {{ Math.round(r.confidence * 100) }}%</template>
              </el-tag>
              <el-tag v-if="r.mark !== 'none'" class="mark" size="small" type="info" effect="dark">{{ markMap[r.mark] }}</el-tag>
            </div>
            <div class="body">
              <a :href="itemLink(r)" target="_blank" rel="noopener" class="title">{{ r.item.title }}</a>
              <div class="price-row">
                <span class="price">{{ fmtMoney(r.item.price) }}</span>
                <span v-if="r.item.orig_price" class="orig">{{ fmtMoney(r.item.orig_price) }}</span>
                <el-tag size="small" :type="dealType(r.deal_label)" effect="plain">{{ r.deal_label }}</el-tag>
              </div>
              <div class="meta muted small">
                {{ r.item.area || '未知地区' }} · {{ r.item.seller_nick || '卖家' }}
                <template v-if="r.item.seller_zhima"> · {{ r.item.seller_zhima }}</template>
                <template v-if="r.item.want_cnt"> · {{ r.item.want_cnt }} 人想要</template>
              </div>
              <div class="meta muted small">
                <template v-if="!filters.task_id">{{ taskName(r.task_id) }} · </template>{{ fmtRelative(r.created_at) }}
              </div>

              <div v-if="r.reason || r.filter_reasons.length" class="reason">
                {{ r.reason || r.filter_reasons.join('；') }}
              </div>
              <div v-if="r.risk_tags.length" class="tags">
                <el-tag v-for="tg in r.risk_tags" :key="tg" size="small" type="danger" effect="light">{{ tg }}</el-tag>
              </div>
              <div v-if="r.need_confirm.length" class="confirm">
                <div class="small label">需确认</div>
                <ul>
                  <li v-for="c in r.need_confirm" :key="c">{{ c }}</li>
                </ul>
              </div>
              <div v-if="r.questions.length" class="questions">
                <div class="q-head">
                  <span class="small label">可以问卖家</span>
                  <el-button link size="small" :icon="CopyDocument" @click="copyText(r.questions.join('\n'))">复制全部</el-button>
                </div>
                <div v-for="q in r.questions" :key="q" class="q" title="点击复制" @click="copyText(q)">{{ q }}</div>
              </div>
            </div>
            <div class="actions">
              <div class="marks">
                <el-button size="small" :type="r.mark === 'favorite' ? 'warning' : 'default'" @click="mark(r, 'favorite')">收藏</el-button>
                <el-button size="small" :type="r.mark === 'seen' ? 'primary' : 'default'" @click="mark(r, 'seen')">已看</el-button>
                <el-button size="small" :type="r.mark === 'ignored' ? 'info' : 'default'" @click="mark(r, 'ignored')">不感兴趣</el-button>
                <el-button size="small" :type="r.mark === 'bought' ? 'success' : 'default'" @click="mark(r, 'bought')">已买</el-button>
              </div>
              <div class="links">
                <el-button size="small" link type="warning" :icon="DataAnalysis" @click="openAnalysis(r)">商品/商家分析</el-button>
                <el-button size="small" link :icon="TrendCharts" @click="openHistory(r)">价格走势</el-button>
                <el-button size="small" link type="primary" :icon="Bell" @click="watchPrice(r)">价格监控</el-button>
                <el-button size="small" link type="success" :icon="Upload" @click="quickResell(r)">转手发品</el-button>
                <el-button size="small" link type="primary" :icon="Link" tag="a" :href="itemLink(r)" target="_blank">打开</el-button>
              </div>
            </div>
          </el-card>
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

    <SmartTaskDialog v-model="dialog.open" :task="dialog.task" :preset="dialog.preset" @saved="onSaved" />

    <el-drawer v-model="analysis.open" size="560px" destroy-on-close>
      <template #header>
        <div class="ellipsis drawer-title">{{ analysis.result?.item.title || '商品分析' }}</div>
      </template>
      <ItemAnalysisPanel v-if="analysis.result" :item-id="analysis.result.item_id" :task-id="analysis.result.task_id" :initial-tab="analysis.tab" />
    </el-drawer>

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
/* 快速新建 */
.quick {
  display: flex;
  gap: 8px;
  padding: 14px;
  border-radius: 12px;
  background: linear-gradient(120deg, rgba(30, 158, 106, 0.1), rgba(30, 158, 106, 0.02) 60%, rgba(64, 158, 255, 0.06));
  border: 1px solid rgba(30, 158, 106, 0.15);
}
.quick-input {
  flex: 1;
}
.quick .el-button + .el-button {
  margin-left: 0;
}

/* 两栏布局 */
.layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
  margin-top: 12px;
}

/* 左栏任务 */
.tasks {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: calc(100vh - 140px);
  overflow-y: auto;
  padding: 2px;
  min-height: 80px;
}
.tasks-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-weight: 600;
  padding: 0 4px;
}
.tasks-empty {
  padding: 12px;
  line-height: 1.6;
  background: #fff;
  border: 1px dashed var(--xh-border, #e5e7eb);
  border-radius: 10px;
}
.task {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--xh-border, #e5e7eb);
  background: #fff;
  cursor: pointer;
  text-align: left;
  transition: all 0.18s ease;
  outline: none;
}
.task:hover {
  border-color: rgba(30, 158, 106, 0.5);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
.task.active {
  border-color: var(--xh-primary, #1e9e6a);
  background: rgba(30, 158, 106, 0.05);
  box-shadow: 0 0 0 2px rgba(30, 158, 106, 0.12);
}
.task.all {
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
  font: inherit;
}
.task.disabled .t-name {
  color: #606266;
}
.t-row {
  display: flex;
  align-items: center;
  gap: 6px;
  justify-content: space-between;
}
.t-name {
  font-weight: 600;
  color: var(--xh-text, #1f2329);
  min-width: 0;
}
.t-badge {
  flex-shrink: 0;
  min-width: 20px;
  padding: 0 6px;
  height: 20px;
  line-height: 20px;
  border-radius: 10px;
  text-align: center;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  background: var(--xh-primary, #1e9e6a);
}
.t-kw {
  color: #606266;
}
.t-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--xh-muted, #8a919f);
  flex-wrap: wrap;
}
.t-paused {
  color: var(--el-color-danger);
  line-height: 1.4;
}
.t-ops {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
  padding-top: 6px;
  border-top: 1px dashed var(--xh-border, #e5e7eb);
  cursor: default;
}
.t-ops .el-button + .el-button {
  margin-left: 0;
}
.t-ops .el-switch {
  margin-left: auto;
}
.err {
  color: var(--el-color-danger);
}

/* 右栏结果 */
.results {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.filters :deep(.el-card__body) {
  padding: 12px;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.scope {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-right: auto;
  min-width: 0;
}
.f-sel {
  width: 150px;
}
.f-q {
  width: 180px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
  min-height: 120px;
}
.card {
  display: flex;
  flex-direction: column;
}
.card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.img-wrap {
  position: relative;
  aspect-ratio: 4 / 3;
  background: #f2f3f5;
}
.img {
  width: 100%;
  height: 100%;
  display: block;
}
.img-err {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--xh-muted);
}
.verdict {
  position: absolute;
  left: 8px;
  top: 8px;
}
.mark {
  position: absolute;
  right: 8px;
  top: 8px;
}
.body {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
}
.title {
  font-weight: 600;
  color: var(--xh-text);
  text-decoration: none;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.4;
}
.title:hover {
  color: var(--xh-primary);
}
.price-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.price {
  color: #f56c6c;
  font-size: 20px;
  font-weight: 700;
}
.orig {
  color: var(--xh-muted);
  text-decoration: line-through;
  font-size: 12px;
}
.reason {
  font-size: 13px;
  line-height: 1.5;
  background: #f7f8fa;
  border-radius: 6px;
  padding: 8px;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.label {
  font-weight: 600;
  color: #606266;
}
.confirm ul {
  margin: 4px 0 0;
  padding-left: 18px;
  font-size: 13px;
  color: #e6a23c;
}
.q-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.q {
  font-size: 13px;
  padding: 6px 8px;
  margin-top: 4px;
  background: var(--el-color-primary-light-9);
  border-radius: 6px;
  cursor: pointer;
}
.q:hover {
  background: var(--el-color-primary-light-8);
}
.actions {
  border-top: 1px solid var(--xh-border);
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.marks {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.marks .el-button + .el-button {
  margin-left: 0;
}
.links {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 4px;
}
.links .el-button + .el-button {
  margin-left: 0;
}
.drawer-title {
  font-weight: 600;
  color: var(--xh-text);
}
.empty-state-box {
  grid-column: 1 / -1;
  padding: 40px 0;
  display: flex;
  justify-content: center;
}
.empty-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  margin-top: 12px;
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
  .quick-input {
    flex-basis: 100%;
  }
  .f-sel,
  .f-q {
    width: calc(50% - 4px);
  }
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
