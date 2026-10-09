<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { CopyDocument, Download, Link, Refresh, Search, TrendCharts } from '@element-plus/icons-vue'
import {
  exportResults,
  listResults,
  listTasks,
  markResult,
  priceHistory,
  type ResultOut,
  type TaskOut,
  type UserMark,
} from '@/api/buyer'
import EChart from '@/components/EChart.vue'
import { copyText, fmtMoney, fmtRelative, fmtTime, itemUrl, markMap, verdictMap } from '@/utils/format'

const route = useRoute()
const PAGE = 40

const tasks = ref<TaskOut[]>([])
const results = ref<ResultOut[]>([])
const loading = ref(false)
const hasMore = ref(false)
const exporting = ref(false)

const filters = reactive({
  task_id: (route.query.task_id ? Number(route.query.task_id) : undefined) as number | undefined,
  verdict: 'default',
  mark: '',
  sort: 'newest' as 'newest' | 'price_asc' | 'deal',
  q: '',
})

async function load(append = false) {
  loading.value = true
  try {
    const rows = await listResults({
      task_id: filters.task_id || undefined,
      verdict: filters.verdict,
      mark: filters.mark || undefined,
      sort: filters.sort,
      q: filters.q.trim() || undefined,
      limit: PAGE,
      offset: append ? results.value.length : 0,
    })
    results.value = append ? [...results.value, ...rows] : rows
    hasMore.value = rows.length === PAGE
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  load()
  tasks.value = await listTasks().catch(() => [])
})

const taskName = computed(() => {
  const m = new Map(tasks.value.map((t) => [t.id, t.name]))
  return (id: number) => m.get(id) || `任务 #${id}`
})

async function mark(r: ResultOut, m: UserMark) {
  const next: UserMark = r.mark === m ? 'none' : m
  try {
    await markResult(r.id, next)
    r.mark = next
    if (next === 'ignored' && !filters.mark) {
      // 不感兴趣的结果默认隐藏
      results.value = results.value.filter((x) => x.id !== r.id)
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

// ---------------------------------------------------------------- 价格走势
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
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>选品雷达 · 好货看板</h2>
        <div class="sub">AI 判定为推荐 / 有条件推荐的商品，附带风险点与给卖家的提问</div>
      </div>
      <div class="toolbar">
        <el-button :icon="Refresh" :loading="loading" @click="load()">刷新</el-button>
        <el-button :icon="Download" :loading="exporting" @click="doExport">导出 CSV</el-button>
      </div>
    </div>

    <el-card shadow="never" class="filters">
      <div class="toolbar">
        <el-select v-model="filters.task_id" clearable placeholder="全部任务" class="f-task" @change="load()">
          <el-option v-for="t in tasks" :key="t.id" :value="t.id" :label="t.name" />
        </el-select>
        <el-select v-model="filters.verdict" class="f-sel" @change="load()">
          <el-option value="default" label="推荐 + 有条件" />
          <el-option value="recommend" label="仅推荐" />
          <el-option value="conditional" label="有条件推荐" />
          <el-option value="reject" label="不推荐" />
          <el-option value="filtered" label="已筛除" />
          <el-option value="all" label="全部" />
        </el-select>
        <el-select v-model="filters.mark" clearable placeholder="全部标记" class="f-sel" @change="load()">
          <el-option v-for="(label, k) in markMap" :key="k" :value="k" :label="label" />
        </el-select>
        <el-select v-model="filters.sort" class="f-sel" @change="load()">
          <el-option value="newest" label="最新发现" />
          <el-option value="price_asc" label="价格最低" />
          <el-option value="deal" label="性价比最高" />
        </el-select>
        <el-input v-model="filters.q" placeholder="标题关键词" clearable class="f-q" :prefix-icon="Search" @keyup.enter="load()" @clear="load()" />
      </div>
    </el-card>

    <div v-loading="loading && !results.length" class="grid">
      <el-empty v-if="!loading && !results.length" description="暂无结果，去「监控任务」运行一次试试" class="empty" />
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
          <div class="meta muted small">{{ taskName(r.task_id) }} · {{ fmtRelative(r.created_at) }}</div>

          <div v-if="r.reason || r.filter_reasons.length" class="reason">
            {{ r.reason || r.filter_reasons.join('；') }}
          </div>
          <div v-if="r.risk_tags.length" class="tags">
            <el-tag v-for="t in r.risk_tags" :key="t" size="small" type="danger" effect="light">{{ t }}</el-tag>
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
            <el-button size="small" link :icon="TrendCharts" @click="openHistory(r)">价格走势</el-button>
            <el-button size="small" link type="primary" :icon="Link" tag="a" :href="itemLink(r)" target="_blank">打开</el-button>
          </div>
        </div>
      </el-card>
    </div>

    <div v-if="hasMore" class="more">
      <el-button :loading="loading" @click="load(true)">加载更多</el-button>
    </div>

    <el-dialog v-model="history.open" title="价格走势" width="640px">
      <div class="muted small ellipsis">{{ history.title }}</div>
      <div v-loading="history.loading">
        <el-empty v-if="!history.loading && history.points.length < 2" :description="history.points.length ? `仅有一次记录：¥${history.points[0]?.price}` : '暂无价格记录'" :image-size="60" />
        <EChart v-else-if="history.points.length" :option="historyOption" height="280px" />
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.filters :deep(.el-card__body) {
  padding: 12px;
}
.f-task {
  width: 180px;
}
.f-sel {
  width: 140px;
}
.f-q {
  width: 200px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
  min-height: 120px;
}
.empty {
  grid-column: 1 / -1;
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
}
.more {
  text-align: center;
}
@media (max-width: 768px) {
  .f-task,
  .f-sel,
  .f-q {
    width: calc(50% - 4px);
  }
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
