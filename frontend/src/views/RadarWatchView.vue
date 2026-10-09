<script setup lang="ts">
import { computed, onActivated, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Bell, Delete, Edit, Link, Plus, Refresh, TrendCharts } from '@element-plus/icons-vue'
import {
  WATCH_INTERVALS,
  checkWatch,
  createWatch,
  deleteWatch,
  listWatches,
  priceHistory,
  updateWatch,
  type WatchOut,
  type WatchSettings,
  type WatchStatus,
} from '@/api/buyer'
import EChart from '@/components/EChart.vue'
import RadarNav from '@/components/RadarNav.vue'
import { useAccountsStore } from '@/stores/accounts'
import { useKeepScroll } from '@/composables/useKeepScroll'
import { useMobile } from '@/composables/useMobile'
import { fmtMoney, fmtRelative, fmtTime, itemUrl } from '@/utils/format'

defineOptions({ name: 'RadarWatchView' })
useKeepScroll()

const route = useRoute()
const router = useRouter()
const accounts = useAccountsStore()
const isMobile = useMobile()

const watches = ref<WatchOut[]>([])
const loading = ref(false)
const busy = reactive<Record<string, boolean>>({})
const filter = ref<'all' | WatchStatus>('all')

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    watches.value = await listWatches()
  } finally {
    loading.value = false
  }
}

function checkRouteAdd() {
  // 从智能搜索 / 实时搜货带过来的商品：直接打开添加弹窗
  const add = route.query.add
  if (typeof add === 'string' && add) {
    const price = Number(route.query.price) || null
    openCreate(add, String(route.query.title || ''), price)
    router.replace({ path: route.path })
  }
}

onMounted(async () => {
  accounts.load().catch(() => undefined)
  await load()
  checkRouteAdd()
})

onActivated(() => {
  checkRouteAdd()
  load(true)
})

const statusMap: Record<WatchStatus, { label: string; type: 'success' | 'warning' | 'info' | 'danger' }> = {
  watching: { label: '监控中', type: 'success' },
  triggered: { label: '已到价', type: 'warning' },
  paused: { label: '已暂停', type: 'info' },
  ended: { label: '已结束', type: 'danger' },
}

const counts = computed(() => {
  const c: Record<string, number> = { all: watches.value.length, watching: 0, triggered: 0, paused: 0, ended: 0 }
  for (const w of watches.value) c[w.status] = (c[w.status] || 0) + 1
  return c
})

const shown = computed(() => (filter.value === 'all' ? watches.value : watches.value.filter((w) => w.status === filter.value)))

function change(w: WatchOut): number | null {
  if (!w.base_price || w.last_price == null) return null
  return ((w.last_price - w.base_price) / w.base_price) * 100
}

/** 距离目标价还差多少（百分比），用于进度条 */
function progress(w: WatchOut): number | null {
  if (w.target_price == null || !w.base_price || w.last_price == null) return null
  const span = w.base_price - w.target_price
  if (span <= 0) return 100
  return Math.max(0, Math.min(100, ((w.base_price - w.last_price) / span) * 100))
}

function conditionText(w: WatchOut): string {
  const parts: string[] = []
  if (w.target_price != null) parts.push(`≤ ¥${w.target_price}`)
  if (w.drop_percent) parts.push(`降幅 ≥ ${w.drop_percent}%`)
  return parts.join(' 或 ')
}

function intervalLabel(v: number) {
  return WATCH_INTERVALS.find((i) => i.value === v)?.label.replace('（推荐）', '') || `每 ${v} 分钟`
}

function settingsOf(w: WatchOut): WatchSettings {
  return {
    target_price: w.target_price,
    drop_percent: w.drop_percent,
    interval_minutes: w.interval_minutes,
    account_id: w.account_id,
    note: w.note,
  }
}

function replace(w: WatchOut) {
  const i = watches.value.findIndex((x) => x.id === w.id)
  if (i >= 0) watches.value[i] = w
}

async function toggle(w: WatchOut, enabled: boolean) {
  busy[`en-${w.id}`] = true
  try {
    replace(await updateWatch(w.id, { ...settingsOf(w), enabled }))
    ElMessage.success(enabled ? '已重新开启监控' : '已暂停监控')
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[`en-${w.id}`] = false
  }
}

async function checkNow(w: WatchOut) {
  busy[`chk-${w.id}`] = true
  try {
    const res = await checkWatch(w.id)
    replace(res)
    if (res.status === 'triggered' && w.status !== 'triggered') ElMessage.success('已到达目标价，提醒已发送')
    else if (res.status === 'ended') ElMessage.warning(res.ended_reason || '商品已下架')
    else ElMessage.success(`当前价格 ${fmtMoney(res.last_price)}`)
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[`chk-${w.id}`] = false
  }
}

async function remove(w: WatchOut) {
  await ElMessageBox.confirm(`不再监控「${w.title || w.item_id}」？`, '删除监控', { type: 'warning' })
  await deleteWatch(w.id)
  watches.value = watches.value.filter((x) => x.id !== w.id)
  ElMessage.success('已删除')
}

// ---------------------------------------------------------------- 添加 / 编辑
const emptyForm = () => ({
  item: '',
  target_price: null as number | null,
  drop_percent: null as number | null,
  interval_minutes: 60,
  account_id: null as number | null,
  note: '',
})

const edit = reactive({
  open: false,
  saving: false,
  watch: null as WatchOut | null,
  hint: { title: '', price: null as number | null },
  form: emptyForm(),
})

function openCreate(item = '', title = '', price: number | null = null) {
  Object.assign(edit, {
    open: true,
    watch: null,
    hint: { title, price },
    form: { ...emptyForm(), item, target_price: price ? Math.floor(price * 0.9) : null },
  })
}

function openEdit(w: WatchOut) {
  Object.assign(edit, {
    open: true,
    watch: w,
    hint: { title: w.title, price: w.last_price },
    form: { ...emptyForm(), ...settingsOf(w), item: w.item_id },
  })
}

async function save() {
  const f = edit.form
  if (!edit.watch && !f.item.trim()) return ElMessage.warning('请粘贴商品链接或填写商品 ID')
  if (f.target_price == null && !f.drop_percent) return ElMessage.warning('请至少设置目标价或降幅提醒中的一项')
  const settings: WatchSettings = {
    target_price: f.target_price,
    drop_percent: f.drop_percent || null,
    interval_minutes: f.interval_minutes,
    account_id: f.account_id,
    note: f.note.trim(),
  }
  edit.saving = true
  try {
    if (edit.watch) {
      replace(await updateWatch(edit.watch.id, { ...settings, enabled: edit.watch.enabled }))
      ElMessage.success('已保存')
    } else {
      const w = await createWatch({ ...settings, item: f.item.trim() })
      watches.value.unshift(w)
      ElMessage.success(`已开始监控，当前价格 ${fmtMoney(w.last_price)}`)
    }
    edit.open = false
  } catch {
    /* 拦截器已提示 */
  } finally {
    edit.saving = false
  }
}

// ---------------------------------------------------------------- 价格走势
const history = reactive({ open: false, loading: false, watch: null as WatchOut | null, points: [] as { price: number; seen_at: string }[] })

async function openHistory(w: WatchOut) {
  Object.assign(history, { open: true, loading: true, watch: w, points: [] })
  try {
    history.points = await priceHistory(w.item_id)
  } finally {
    history.loading = false
  }
}

const historyOption = computed(() => {
  const target = history.watch?.target_price
  return {
    grid: { left: 52, right: 24, top: 28, bottom: 32 },
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
        markLine:
          target != null
            ? {
                symbol: 'none',
                lineStyle: { color: '#e6a23c', type: 'dashed' },
                label: { formatter: `目标 ¥${target}`, position: 'insideEndTop' },
                data: [{ yAxis: target }],
              }
            : undefined,
      },
    ],
  }
})
</script>

<template>
  <div class="page">
    <RadarNav current="watch">
      <template #actions>
        <el-button :icon="Refresh" :loading="loading" @click="load()">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate()">添加监控</el-button>
      </template>
    </RadarNav>

    <div class="summary">
      <button
        v-for="k in (['all', 'watching', 'triggered', 'paused', 'ended'] as const)"
        :key="k"
        type="button"
        class="sum-item"
        :class="[`s-${k}`, { active: filter === k }]"
        @click="filter = k"
      >
        <span class="sum-num">{{ counts[k] || 0 }}</span>
        <span class="sum-label">{{ k === 'all' ? '全部' : statusMap[k].label }}</span>
      </button>
    </div>

    <div v-loading="loading" class="grid">
      <div v-if="!loading && !shown.length" class="empty-box">
        <el-empty :description="watches.length ? '该状态下暂无监控' : '暂无监控商品'">
          <template v-if="!watches.length">
            <div class="empty-actions">
              <el-button type="primary" :icon="Plus" @click="openCreate()">粘贴链接添加</el-button>
              <el-button @click="router.push('/radar/smart')">去智能搜索挑选</el-button>
            </div>
          </template>
        </el-empty>
      </div>

      <el-card v-for="w in shown" :key="w.id" shadow="hover" class="card" :class="`c-${w.status}`" :body-style="{ padding: '0' }">
        <div class="head">
          <el-image :src="w.image_url" fit="cover" class="thumb" referrerpolicy="no-referrer">
            <template #error><div class="img-err">无图</div></template>
          </el-image>
          <div class="head-main">
            <a :href="w.link || itemUrl(w.item_id)" target="_blank" rel="noopener" class="title">{{ w.title || `商品 ${w.item_id}` }}</a>
            <div class="tags">
              <el-tag size="small" :type="statusMap[w.status].type" effect="dark">{{ statusMap[w.status].label }}</el-tag>
              <el-tag size="small" type="info" effect="plain">{{ intervalLabel(w.interval_minutes) }}</el-tag>
            </div>
            <div v-if="w.note" class="note small">{{ w.note }}</div>
          </div>
        </div>

        <div class="prices">
          <div class="p-now">
            <span class="p-label">当前</span>
            <span class="p-val">{{ fmtMoney(w.last_price) }}</span>
            <span v-if="change(w) !== null && Math.abs(change(w)!) >= 0.5" class="p-change" :class="change(w)! < 0 ? 'down' : 'up'">
              {{ change(w)! < 0 ? '↓' : '↑' }}{{ Math.abs(change(w)!).toFixed(1) }}%
            </span>
          </div>
          <div class="p-meta small">
            <span>加入时 {{ fmtMoney(w.base_price) }}</span>
            <span>最低 {{ fmtMoney(w.lowest_price) }}</span>
          </div>
          <div class="cond">
            <el-icon><Bell /></el-icon>
            <span>提醒条件：{{ conditionText(w) }}</span>
          </div>
          <el-progress
            v-if="progress(w) !== null && w.status !== 'ended'"
            :percentage="Math.round(progress(w)!)"
            :stroke-width="6"
            :show-text="false"
            :status="w.status === 'triggered' ? 'warning' : undefined"
            class="prog"
          />
        </div>

        <div class="state small">
          <template v-if="w.status === 'triggered'">🎯 {{ fmtRelative(w.triggered_at) }}到价，已提醒并暂停</template>
          <template v-else-if="w.status === 'ended'">⛔ {{ w.ended_reason || '商品已下架' }}</template>
          <template v-else>上次检查 {{ w.last_checked_at ? fmtRelative(w.last_checked_at) : '—' }}</template>
          <el-tooltip v-if="w.last_error" :content="w.last_error">
            <div class="err ellipsis">检查失败：{{ w.last_error }}</div>
          </el-tooltip>
        </div>

        <div class="actions">
          <el-switch
            :model-value="w.enabled"
            :disabled="w.status === 'ended'"
            :loading="busy[`en-${w.id}`]"
            size="small"
            inline-prompt
            active-text="开"
            inactive-text="停"
            @change="(v: string | number | boolean) => toggle(w, !!v)"
          />
          <div class="ops">
            <el-button size="small" link :icon="TrendCharts" @click="openHistory(w)">走势</el-button>
            <el-button size="small" link type="primary" :icon="Refresh" :loading="busy[`chk-${w.id}`]" :disabled="w.status === 'ended'" @click="checkNow(w)">检查</el-button>
            <el-button size="small" link :icon="Edit" @click="openEdit(w)">编辑</el-button>
            <el-button size="small" link :icon="Link" tag="a" :href="w.link || itemUrl(w.item_id)" target="_blank">打开</el-button>
            <el-button size="small" link type="danger" :icon="Delete" @click="remove(w)" />
          </div>
        </div>
      </el-card>
    </div>

    <!-- 添加 / 编辑 -->
    <el-dialog v-model="edit.open" :title="edit.watch ? '编辑价格监控' : '添加价格监控'" width="520px" :fullscreen="isMobile" destroy-on-close>
      <el-form label-width="96px" :label-position="isMobile ? 'top' : 'right'">
        <el-form-item v-if="!edit.watch" label="商品" required>
          <el-input v-model="edit.form.item" placeholder="粘贴闲鱼商品链接，或直接填写商品 ID" clearable />
          <div v-if="edit.hint.title" class="form-tip ellipsis">{{ edit.hint.title }}</div>
        </el-form-item>
        <el-form-item v-else label="商品">
          <div class="ellipsis">{{ edit.watch.title }}</div>
        </el-form-item>
        <el-form-item v-if="edit.hint.price" label="当前价格">
          <span class="cur-price">{{ fmtMoney(edit.hint.price) }}</span>
        </el-form-item>
        <el-form-item label="目标价">
          <el-input-number v-model="edit.form.target_price" :min="0.01" :precision="2" :controls="false" placeholder="不设置" :value-on-clear="null" class="w160" />
          <span class="muted ml">元及以下时提醒</span>
        </el-form-item>
        <el-form-item label="降幅提醒">
          <el-input-number v-model="edit.form.drop_percent" :min="1" :max="90" :controls="false" placeholder="不设置" :value-on-clear="null" class="w160" />
          <span class="muted ml">% （较{{ edit.watch ? '开启' : '加入' }}时价格）</span>
          <div class="form-tip">两个条件满足任一即提醒，提醒一次后自动暂停，避免反复打扰。</div>
        </el-form-item>
        <el-form-item label="检查频率">
          <el-select v-model="edit.form.interval_minutes" class="w240">
            <el-option v-for="i in WATCH_INTERVALS" :key="i.value" :value="i.value" :label="i.label" />
          </el-select>
          <div class="form-tip">每次检查查询一次商品详情。频率越高，触发风控的可能越大。</div>
        </el-form-item>
        <el-form-item label="查询账号">
          <el-select v-model="edit.form.account_id" clearable placeholder="匿名查询（推荐）" class="w240">
            <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="edit.form.note" maxlength="256" placeholder="例如：想自用，3000 以下就入" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="edit.open = false">取消</el-button>
        <el-button type="primary" :loading="edit.saving" @click="save">{{ edit.watch ? '保存' : '开始监控' }}</el-button>
      </template>
    </el-dialog>

    <!-- 价格走势 -->
    <el-dialog v-model="history.open" title="价格走势" width="640px">
      <div class="muted small ellipsis">{{ history.watch?.title }}</div>
      <div v-loading="history.loading">
        <el-empty v-if="!history.loading && history.points.length < 2" :description="history.points.length ? `价格暂无变化：¥${history.points[0]?.price}` : '暂无价格记录'" :image-size="60" />
        <EChart v-else-if="history.points.length" :option="historyOption" height="280px" />
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.summary {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}
.sum-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 10px 14px;
  border-radius: var(--xh-radius-md);
  border: 1px solid var(--xh-border);
  background: var(--xh-card);
  cursor: pointer;
  transition: all 0.18s ease;
  text-align: left;
}
.sum-item:hover {
  border-color: var(--xh-primary);
  transform: translateY(-1px);
}
.sum-item.active {
  border-color: var(--xh-primary);
  box-shadow: 0 0 0 2px var(--xh-primary-soft);
}
.sum-num {
  font-size: var(--xh-fs-xl);
  font-weight: 700;
  color: var(--xh-text);
  line-height: 1.2;
}
.sum-label {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}
.s-watching .sum-num {
  color: var(--xh-primary);
}
.s-triggered .sum-num {
  color: var(--xh-warning-text);
}
.s-ended .sum-num {
  color: var(--xh-disabled);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
  min-height: 120px;
  margin-top: 12px;
}
.empty-box {
  grid-column: 1 / -1;
  padding: 32px 0;
}
.empty-tip {
  margin: 0 0 12px;
}
.empty-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
}
.card {
  display: flex;
  flex-direction: column;
  border-top: 3px solid transparent;
  transition: transform 0.18s ease;
}
.card:hover {
  transform: translateY(-2px);
}
.card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.c-watching {
  border-top-color: var(--xh-primary);
}
.c-triggered {
  border-top-color: var(--xh-warning);
}
.c-paused {
  border-top-color: var(--xh-disabled);
}
.c-ended {
  border-top-color: var(--xh-danger);
  opacity: 0.75;
}
.head {
  display: flex;
  gap: 12px;
  padding: 12px 12px 0;
}
.thumb {
  width: 72px;
  height: 72px;
  border-radius: var(--xh-radius-sm);
  flex-shrink: 0;
  background: var(--xh-fill);
}
.img-err {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}
.head-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
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
.tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.note {
  color: var(--xh-text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.prices {
  padding: 10px 12px 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.p-now {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.p-label {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}
.p-val {
  font-size: var(--xh-fs-xl);
  font-weight: 700;
  color: var(--xh-price);
}
.p-change {
  font-size: var(--xh-fs-xs);
  font-weight: 600;
  padding: 1px 6px;
  border-radius: var(--xh-radius-md);
}
.p-change.down {
  color: var(--xh-primary);
  background: var(--xh-primary-soft);
}
.p-change.up {
  color: var(--xh-danger);
  background: var(--el-color-danger-light-9);
}
.p-meta {
  display: flex;
  gap: 12px;
  color: var(--xh-muted);
}
.cond {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--xh-fs-sm);
  color: var(--xh-text-2);
  margin-top: 2px;
}
.prog {
  margin-top: 4px;
}
.state {
  padding: 8px 12px;
  color: var(--xh-muted);
  flex: 1;
}
.err {
  color: var(--el-color-danger);
  margin-top: 2px;
}
.actions {
  border-top: 1px solid var(--xh-border);
  padding: 8px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.ops {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}
.ops .el-button + .el-button {
  margin-left: 6px;
}
.cur-price {
  color: var(--xh-price);
  font-weight: 700;
  font-size: var(--xh-fs-lg);
}
.ml {
  margin-left: 8px;
}
.w160 {
  width: 160px;
}
.w240 {
  width: 240px;
  max-width: 100%;
}
@media (max-width: 768px) {
  .summary {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
