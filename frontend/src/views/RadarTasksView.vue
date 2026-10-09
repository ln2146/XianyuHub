<script setup lang="ts">
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MagicStick, Plus, Refresh, Search } from '@element-plus/icons-vue'
import {
  createTask,
  deleteTask,
  emptyRules,
  emptyTask,
  generateTask,
  listTasks,
  runTask,
  taskMarket,
  updateTask,
  type MarketStats,
  type TaskIn,
  type TaskOut,
} from '@/api/buyer'
import { useAccountsStore } from '@/stores/accounts'
import { useKeepScroll } from '@/composables/useKeepScroll'
import { useMobile } from '@/composables/useMobile'
import RadarNav from '@/components/RadarNav.vue'
import { fmtMoney, fmtTime, fmtRelative } from '@/utils/format'

defineOptions({ name: 'RadarTasksView' })
useKeepScroll()

const router = useRouter()
const accounts = useAccountsStore()
const isMobile = useMobile()
const tasks = ref<TaskOut[]>([])
const loading = ref(false)
const busy = reactive<Record<string, boolean>>({})
let timer: number | undefined

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    tasks.value = await listTasks()
  } finally {
    loading.value = false
  }
}

function startTimer() {
  if (timer) window.clearInterval(timer)
  timer = window.setInterval(() => {
    if (tasks.value.some((t) => t.running)) load(true)
  }, 5000)
}

function stopTimer() {
  if (timer) {
    window.clearInterval(timer)
    timer = undefined
  }
}

onMounted(() => {
  load()
  accounts.load().catch(() => undefined)
  startTimer()
})

onActivated(() => {
  load(true)
  startTimer()
})

onDeactivated(() => {
  stopTimer()
})

onBeforeUnmount(() => {
  stopTimer()
})

const statusLabel: Record<string, { label: string; type: 'success' | 'danger' | 'warning' }> = {
  ok: { label: '成功', type: 'success' },
  error: { label: '失败', type: 'danger' },
  risk: { label: '风控', type: 'warning' },
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
    ElMessage.success('已开始搜货，结果会陆续出现在好货看板')
    await load(true)
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
    ElMessage.success(enabled ? '已启用定时执行' : '已暂停定时执行')
    await load(true)
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[`en-${t.id}`] = false
  }
}

async function remove(t: TaskOut) {
  await ElMessageBox.confirm(`删除自动搜货「${t.name}」及其全部结果？`, '删除自动搜货', { type: 'warning' })
  await deleteTask(t.id)
  ElMessage.success('已删除')
  await load(true)
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

// ---------------------------------------------------------------- 编辑
const edit = reactive({
  open: false,
  saving: false,
  id: null as number | null,
  form: emptyTask(),
  tab: 'search',
  nl: '',
  generating: false,
})

const cronPresets = [
  { label: '日常巡检 · 每30分钟 (8-23点，推荐)', value: '*/30 8-23 * * *' },
  { label: '急切捡漏 · 每10分钟 (8-23点)', value: '*/10 8-23 * * *' },
  { label: '高频巡检 · 每15分钟 (8-23点)', value: '*/15 8-23 * * *' },
  { label: '平稳巡检 · 每小时一次', value: '0 * * * *' },
  { label: '闲时巡检 · 每2小时一次', value: '0 */2 * * *' },
  { label: '早晚汇总 · 每天9点/21点', value: '0 9,21 * * *' },
]

const selectedCronPreset = ref('*/30 8-23 * * *')

function syncCronPresetFromForm() {
  const match = cronPresets.find((p) => p.value === edit.form.cron)
  selectedCronPreset.value = match ? match.value : 'custom'
}

function onCronPresetChange(val: string | number | boolean | undefined) {
  const str = String(val)
  if (str !== 'custom') {
    edit.form.cron = str
  }
}

function formatCron(cron: string): string {
  if (!cron) return '未设置'
  const preset = cronPresets.find((p) => p.value === cron)
  if (preset) return preset.label.split(' · ')[0] || preset.label
  if (cron === '*/5 * * * *') return '极速捡漏 (每5分)'
  if (cron === '*/10 8-23 * * *') return '急切捡漏 (每10分)'
  if (cron === '*/15 8-23 * * *') return '高频巡检 (每15分)'
  if (cron === '*/30 8-23 * * *') return '日常巡检 (每30分)'
  if (cron === '0 * * * *') return '平稳巡检 (每小时)'
  if (cron === '0 */2 * * *') return '闲时巡检 (每2小时)'
  if (cron === '0 */3 * * *') return '闲时巡检 (每3小时)'
  if (cron === '0 9,21 * * *') return '定时汇总 (早9/晚9)'
  return cron
}

function openCreate() {
  Object.assign(edit, { open: true, id: null, form: emptyTask(), tab: 'search', nl: '' })
  syncCronPresetFromForm()
}
function openEdit(t: TaskOut) {
  Object.assign(edit, { open: true, id: t.id, form: toIn(t), tab: 'search', nl: '' })
  syncCronPresetFromForm()
}

async function generate() {
  if (edit.nl.trim().length < 4) {
    ElMessage.warning('请至少输入 4 个字描述你想买什么')
    return
  }
  edit.generating = true
  try {
    const d = await generateTask(edit.nl.trim())
    const f = edit.form
    f.name = d.name || f.name
    f.keywords = d.keywords?.length ? d.keywords : f.keywords
    f.min_price = d.min_price ?? null
    f.max_price = d.max_price ?? null
    f.province = d.province ?? null
    f.city = d.city ?? null
    f.publish_days = d.publish_days ?? null
    f.personal_only = !!d.personal_only
    f.rules = { ...f.rules, include_all: d.rules?.include_all || [], exclude: d.rules?.exclude || [] }
    f.criteria = d.criteria || f.criteria
    ElMessage.success('已根据描述生成任务，请检查后保存')
  } catch {
    /* 拦截器已提示 */
  } finally {
    edit.generating = false
  }
}

async function save() {
  const f = edit.form
  if (!f.name.trim()) return ElMessage.warning('请填写任务名称')
  if (!f.keywords.length) return ElMessage.warning('至少需要一个搜索关键词')
  if (f.keywords.length > 8) return ElMessage.warning('关键词最多 8 个')
  if (!f.cron.trim()) return ElMessage.warning('请填写执行计划')
  edit.saving = true
  try {
    const body: TaskIn = { ...f, province: f.province || null, city: f.city || null }
    if (edit.id) await updateTask(edit.id, body)
    else await createTask(body)
    ElMessage.success('已保存')
    edit.open = false
    await load(true)
  } catch {
    /* 拦截器已提示 */
  } finally {
    edit.saving = false
  }
}

function statsText(s: Record<string, unknown>) {
  if (!s || !Object.keys(s).length) return ''
  const n = (k: string) => Number(s[k] ?? 0)
  return `抓取 ${n('fetched')} · 新增 ${n('new')} · 判定 ${n('evaluated')} · 推荐 ${n('recommended')}`
}
</script>

<template>
  <div class="page">
    <RadarNav current="tasks">
      <template #actions>
        <el-button :icon="Refresh" :loading="loading" @click="load()">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新建自动搜货</el-button>
      </template>
    </RadarNav>

    <el-card shadow="never">
      <div class="table-wrap">
        <el-table v-loading="loading" :data="tasks">
          <template #empty>
            <div class="table-empty-box">
              <el-empty description="还没有自动搜货，可以用一句话描述让 AI 帮你生成；搜到的好货会出现在好货看板">
                <div class="empty-btn-group">
                  <el-button type="primary" :icon="Plus" @click="openCreate">新建自动搜货</el-button>
                  <el-button :icon="Search" @click="router.push('/radar/search')">先去实时搜货</el-button>
                </div>
              </el-empty>
            </div>
          </template>
          <el-table-column label="自动搜货" min-width="200">
            <template #default="{ row }">
              <div class="name">
                {{ row.name }}
                <el-tag v-if="row.running" size="small" type="primary" effect="dark" class="ml">运行中</el-tag>
              </div>
              <div class="kw">
                <el-tag v-for="k in row.keywords" :key="k" size="small" effect="plain">{{ k }}</el-tag>
              </div>
              <div class="muted small">
                {{ row.min_price || row.max_price ? `${row.min_price ?? 0} - ${row.max_price ?? '不限'} 元` : '价格不限' }}
                · {{ row.decision_mode === 'ai' ? 'AI 判定' : '仅规则' }}
                <template v-if="row.account_id"> · 账号 {{ accounts.nameOf(row.account_id) }}</template>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="计划频率" width="190">
            <template #default="{ row }">
              <div class="cron-plan-cell">
                <el-tag size="small" type="info" effect="plain" class="mb-xs">{{ formatCron(row.cron) }}</el-tag>
                <div class="cron-switch-row">
                  <el-switch
                    :model-value="row.enabled"
                    :loading="busy[`en-${row.id}`]"
                    size="small"
                    active-text="启用"
                    inactive-text="暂停"
                    inline-prompt
                    @change="(v: string | number | boolean) => toggle(row as TaskOut, !!v)"
                  />
                  <span class="mono smaller muted ml-s">{{ row.cron }}</span>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="上次运行" min-width="220">
            <template #default="{ row }">
              <template v-if="row.last_run_at">
                <div>
                  <el-tag v-if="row.last_status" size="small" :type="statusLabel[row.last_status]?.type || 'info'">
                    {{ statusLabel[row.last_status]?.label || row.last_status }}
                  </el-tag>
                  <span class="small muted ml">{{ fmtRelative(row.last_run_at) }}</span>
                </div>
                <div class="small muted">{{ statsText(row.last_stats) }}</div>
                <el-tooltip v-if="row.last_error" :content="row.last_error">
                  <div class="small err ellipsis">{{ row.last_error }}</div>
                </el-tooltip>
              </template>
              <span v-else class="muted small">尚未运行</span>
              <el-alert v-if="row.paused_reason" :title="`已自动暂停：${row.paused_reason}`" type="error" :closable="false" class="paused" />
            </template>
          </el-table-column>
          <el-table-column label="结果（好货看板）" width="170">
            <template #default="{ row }">
              <el-link type="primary" @click="router.push({ path: '/radar/results', query: { task_id: row.id } })">
                推荐 {{ row.result_counts.recommend || 0 }} · 有条件 {{ row.result_counts.conditional || 0 }}
              </el-link>
              <div class="muted small">不推荐 {{ row.result_counts.reject || 0 }} · 筛除 {{ row.result_counts.filtered || 0 }}</div>
            </template>
          </el-table-column>
          <el-table-column label="操作" :width="isMobile ? 110 : 250" :fixed="isMobile ? undefined : 'right'">
            <template #default="{ row }">
              <div class="ops">
                <el-button size="small" type="primary" :loading="busy[`run-${row.id}`]" :disabled="row.running" @click="run(row as TaskOut)">立即运行</el-button>
                <el-button size="small" @click="openEdit(row as TaskOut)">编辑</el-button>
                <el-dropdown trigger="click">
                  <el-button size="small">更多</el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item @click="openMarket(row as TaskOut)">行情统计</el-dropdown-item>
                      <el-dropdown-item divided @click="remove(row as TaskOut)"><span class="err">删除</span></el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <!-- 编辑任务 -->
    <el-dialog v-model="edit.open" :title="edit.id ? '编辑自动搜货' : '新建自动搜货'" width="760px" top="5vh" :fullscreen="isMobile">
      <div class="nl">
        <el-input
          v-model="edit.nl"
          type="textarea"
          :rows="2"
          placeholder="一句话描述你想买什么，例如：想买一台 2000 元以内的 iPhone 13，128G，电池健康 85% 以上，不要维修过的，最好是同城个人卖家"
        />
        <el-button type="primary" plain :icon="MagicStick" :loading="edit.generating" @click="generate">一句话生成</el-button>
      </div>

      <el-tabs v-model="edit.tab">
        <el-tab-pane label="搜索条件" name="search">
          <el-form label-width="110px" :label-position="isMobile ? 'top' : 'right'">
            <el-form-item label="任务名称" required>
              <el-input v-model="edit.form.name" maxlength="64" />
            </el-form-item>
            <el-form-item label="搜索关键词" required>
              <el-input-tag v-model="edit.form.keywords" placeholder="输入后回车，最多 8 个" :max="8" save-on-blur />
              <div class="form-tip">每个关键词单独搜索一次，结果合并去重。</div>
            </el-form-item>
            <el-form-item label="价格区间">
              <div class="range">
                <el-input-number v-model="edit.form.min_price" :min="0" :controls="false" placeholder="最低" :value-on-clear="null" />
                <span>-</span>
                <el-input-number v-model="edit.form.max_price" :min="0" :controls="false" placeholder="最高" :value-on-clear="null" />
                <span class="muted">元</span>
              </div>
            </el-form-item>
            <el-form-item label="地区">
              <div class="range">
                <el-input v-model="edit.form.province" placeholder="省份，如 广东" clearable class="w160" />
                <el-input v-model="edit.form.city" placeholder="城市，如 深圳" clearable class="w160" />
              </div>
            </el-form-item>
            <el-form-item label="发布时间">
              <el-select v-model="edit.form.publish_days" clearable placeholder="不限" class="w160">
                <el-option :value="1" label="1 天内" />
                <el-option :value="3" label="3 天内" />
                <el-option :value="7" label="7 天内" />
                <el-option :value="14" label="14 天内" />
                <el-option :value="30" label="30 天内" />
              </el-select>
            </el-form-item>
            <el-form-item label="排序">
              <el-radio-group v-model="edit.form.sort">
                <el-radio-button value="newest">最新发布</el-radio-button>
                <el-radio-button value="price_asc">价格从低到高</el-radio-button>
                <el-radio-button value="default">综合</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="抓取页数">
              <el-input-number v-model="edit.form.max_pages" :min="1" :max="5" />
              <div class="form-tip">每页约 30 条，页数越多越容易触发风控。</div>
            </el-form-item>
            <el-form-item label="筛选">
              <el-checkbox v-model="edit.form.personal_only">只看个人闲置</el-checkbox>
              <el-checkbox v-model="edit.form.free_shipping">只看包邮</el-checkbox>
            </el-form-item>
            <el-form-item label="搜索账号">
              <el-select v-model="edit.form.account_id" clearable placeholder="匿名搜索（推荐）" class="w240">
                <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
              </el-select>
              <div class="form-tip">留空使用匿名会话搜索，避免主账号因频繁搜索被风控。</div>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="规则初筛" name="rules">
          <el-form label-width="130px" :label-position="isMobile ? 'top' : 'right'">
            <el-form-item label="标题包含任一">
              <el-input-tag v-model="edit.form.rules.include_any" placeholder="回车添加，为空不限" save-on-blur />
            </el-form-item>
            <el-form-item label="标题必须全部包含">
              <el-input-tag v-model="edit.form.rules.include_all" placeholder="回车添加" save-on-blur />
            </el-form-item>
            <el-form-item label="排除词">
              <el-input-tag v-model="edit.form.rules.exclude" placeholder="标题或描述包含任一则排除，如：维修、配件、求购" save-on-blur />
            </el-form-item>
            <el-form-item label="发货地包含">
              <el-input-tag v-model="edit.form.rules.areas" placeholder="如：深圳、广州，为空不限" save-on-blur />
            </el-form-item>
            <el-form-item label="二次价格过滤">
              <div class="range">
                <el-input-number v-model="edit.form.rules.min_price" :min="0" :controls="false" placeholder="最低" :value-on-clear="null" />
                <span>-</span>
                <el-input-number v-model="edit.form.rules.max_price" :min="0" :controls="false" placeholder="最高" :value-on-clear="null" />
              </div>
            </el-form-item>
            <el-form-item label="发布时间内（小时）">
              <el-input-number v-model="edit.form.rules.max_age_hours" :min="1" placeholder="不限" :value-on-clear="null" />
            </el-form-item>
            <el-form-item label="最低芝麻信用">
              <el-select v-model="edit.form.rules.min_seller_zhima" clearable placeholder="不限" class="w160">
                <el-option value="信用一般" label="信用一般" />
                <el-option value="信用良好" label="信用良好" />
                <el-option value="信用优秀" label="信用优秀" />
                <el-option value="信用极好" label="信用极好" />
              </el-select>
            </el-form-item>
            <el-form-item label="卖家注册天数 ≥">
              <el-input-number v-model="edit.form.rules.min_seller_reg_days" :min="0" placeholder="不限" :value-on-clear="null" />
              <div class="form-tip">需开启「抓取卖家资料」才能生效。</div>
            </el-form-item>
            <el-form-item label="卖家黑名单">
              <el-input-tag v-model="edit.form.rules.blacklist_sellers" placeholder="卖家昵称或 ID" save-on-blur />
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="AI 判定" name="ai">
          <el-form label-width="130px" :label-position="isMobile ? 'top' : 'right'">
            <el-form-item label="判定方式">
              <el-radio-group v-model="edit.form.decision_mode">
                <el-radio-button value="ai">AI 判定</el-radio-button>
                <el-radio-button value="rule">仅规则</el-radio-button>
              </el-radio-group>
              <div class="form-tip">仅规则：通过初筛即推荐，不消耗大模型额度。</div>
            </el-form-item>
            <el-form-item label="判定标准">
              <el-input v-model="edit.form.criteria" type="textarea" :rows="5" placeholder="用自然语言描述你的要求，例如：国行、无拆修、电池健康 ≥85%、屏幕无划痕；价格低于市场价 10% 以上才推荐" />
            </el-form-item>
            <el-form-item label="选项">
              <div class="checks">
                <el-checkbox v-model="edit.form.ai_prescreen">AI 文本粗筛（先用便宜模型淘汰明显不符的）</el-checkbox>
                <el-checkbox v-model="edit.form.analyze_images">分析商品图片</el-checkbox>
                <el-checkbox v-model="edit.form.fetch_seller_profile">抓取卖家资料（更慢，风控风险更高）</el-checkbox>
              </div>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="调度与通知" name="schedule">
          <el-form label-width="130px" :label-position="isMobile ? 'top' : 'right'">
            <el-form-item label="巡检频率" required>
              <el-radio-group v-model="selectedCronPreset" class="cron-radio-list" @change="onCronPresetChange">
                <el-radio v-for="p in cronPresets" :key="p.value" :value="p.value" border class="cron-radio-item">
                  {{ p.label }}
                </el-radio>
                <el-radio value="custom" border class="cron-radio-item">自定义 Cron 表达式</el-radio>
              </el-radio-group>
              <div v-if="selectedCronPreset === 'custom'" class="mt-s" style="width: 100%">
                <el-input v-model="edit.form.cron" placeholder="例如：*/20 9-22 * * *" class="mono w240" />
                <div class="form-tip">标准 5 段 cron：分 时 日 月 周。间隔至少 5 分钟，建议 30 分钟以上。</div>
              </div>
            </el-form-item>
            <el-form-item label="任务开关">
              <el-switch v-model="edit.form.enabled" active-text="启用自动巡检" inactive-text="暂停" />
            </el-form-item>
            <el-form-item label="通知有条件推荐">
              <el-switch v-model="edit.form.notify_conditional" />
              <div class="form-tip">默认只推送「推荐」结果。想盯某件商品降价，请在好货看板里点「价格监控」。</div>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>

      <template #footer>
        <el-button @click="edit.open = false">取消</el-button>
        <el-button type="primary" :loading="edit.saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 行情统计 -->
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
        <div class="form-tip">统计范围：该任务抓取到的全部商品（已剔除离群值）。上次运行：{{ fmtTime(market.task?.last_run_at) }}</div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.name {
  font-weight: 600;
}
.kw {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 4px 0;
}
.ml {
  margin-left: 6px;
}
.err {
  color: var(--el-color-danger);
}
.paused {
  margin-top: 6px;
  padding: 4px 8px;
}
.ops {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ops .el-button + .el-button {
  margin-left: 0;
}
.nl {
  display: flex;
  gap: 8px;
  align-items: stretch;
  margin-bottom: 8px;
  padding: 12px;
  background: var(--el-color-primary-light-9);
  border-radius: 8px;
}
.nl .el-button {
  height: auto;
}
.range {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.w160 {
  width: 160px;
}
.w240 {
  width: 240px;
  max-width: 100%;
}
.checks {
  display: flex;
  flex-direction: column;
}
.presets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
  width: 100%;
}
.cron-plan-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}
.cron-switch-row {
  display: flex;
  align-items: center;
  margin-top: 4px;
}
.cron-radio-list {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
}
.cron-radio-item {
  margin-right: 0 !important;
  margin-left: 0 !important;
  width: 100%;
}
.smaller {
  font-size: 11px;
}
.mb-xs {
  margin-bottom: 4px;
}
.ml-s {
  margin-left: 6px;
}
.table-empty-box {
  padding: 30px 0;
}
.empty-btn-group {
  display: flex;
  gap: 12px;
  justify-content: center;
  margin-top: 12px;
}
@media (max-width: 768px) {
  .nl {
    flex-direction: column;
  }
}
</style>
