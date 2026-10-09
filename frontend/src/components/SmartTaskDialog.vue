<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { MagicStick } from '@element-plus/icons-vue'
import {
  createTask,
  emptyRules,
  emptyTask,
  generateTask,
  updateTask,
  type TaskIn,
  type TaskOut,
} from '@/api/buyer'
import { useAccountsStore } from '@/stores/accounts'
import { useMobile } from '@/composables/useMobile'

/** 智能搜索的新建 / 编辑弹窗：关键词 + 筛选 + 规则初筛 + AI 判定 + 定时频率 */
const props = defineProps<{
  modelValue: boolean
  task?: TaskOut | null
  /** 新建时的预填（如从快速搜索框带入的关键词） */
  preset?: Partial<TaskIn> | null
}>()
const emit = defineEmits<{
  'update:modelValue': [v: boolean]
  saved: [task: TaskOut, created: boolean]
}>()

const accounts = useAccountsStore()
const isMobile = useMobile()

const cronPresets = [
  { label: '日常巡检 · 每30分钟 (8-23点，推荐)', value: '*/30 8-23 * * *' },
  { label: '急切捡漏 · 每10分钟 (8-23点)', value: '*/10 8-23 * * *' },
  { label: '高频巡检 · 每15分钟 (8-23点)', value: '*/15 8-23 * * *' },
  { label: '平稳巡检 · 每小时一次', value: '0 * * * *' },
  { label: '闲时巡检 · 每2小时一次', value: '0 */2 * * *' },
  { label: '早晚汇总 · 每天9点/21点', value: '0 9,21 * * *' },
]

const state = reactive({ saving: false, tab: 'search', nl: '', generating: false, form: emptyTask() })
const selectedCronPreset = ref('*/30 8-23 * * *')

function toIn(t: TaskOut): TaskIn {
  const base = emptyTask()
  const out = { ...base } as Record<string, unknown>
  for (const k of Object.keys(base)) out[k] = (t as unknown as Record<string, unknown>)[k]
  const res = out as unknown as TaskIn
  res.rules = { ...emptyRules(), ...t.rules }
  return res
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    state.form = props.task ? toIn(props.task) : { ...emptyTask(), ...(props.preset || {}) }
    state.tab = 'search'
    state.nl = ''
    const match = cronPresets.find((p) => p.value === state.form.cron)
    selectedCronPreset.value = match ? match.value : 'custom'
    accounts.load().catch(() => undefined)
  },
  { immediate: true },
)

function onCronPresetChange(val: string | number | boolean | undefined) {
  const str = String(val)
  if (str !== 'custom') state.form.cron = str
}

async function generate() {
  if (state.nl.trim().length < 4) {
    ElMessage.warning('请至少输入 4 个字描述你想买什么')
    return
  }
  state.generating = true
  try {
    const d = await generateTask(state.nl.trim())
    const f = state.form
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
    ElMessage.success('已根据描述生成，请检查后保存')
  } catch {
    /* 拦截器已提示 */
  } finally {
    state.generating = false
  }
}

async function save() {
  const f = state.form
  if (!f.name.trim()) return ElMessage.warning('请填写名称')
  if (!f.keywords.length) return ElMessage.warning('至少需要一个搜索关键词')
  if (f.keywords.length > 8) return ElMessage.warning('关键词最多 8 个')
  if (!f.cron.trim()) return ElMessage.warning('请填写搜索频率')
  state.saving = true
  try {
    const body: TaskIn = { ...f, province: f.province || null, city: f.city || null }
    const saved = props.task ? await updateTask(props.task.id, body) : await createTask(body)
    ElMessage.success(props.task ? '已保存' : '已创建，正在搜索…')
    emit('saved', saved, !props.task)
    emit('update:modelValue', false)
  } catch {
    /* 拦截器已提示 */
  } finally {
    state.saving = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="task ? '编辑智能搜索' : '新建智能搜索'"
    width="760px"
    top="5vh"
    :fullscreen="isMobile"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
  >
    <div class="nl">
      <el-input
        v-model="state.nl"
        type="textarea"
        :rows="2"
        placeholder="一句话描述你想买什么，例如：想买一台 2000 元以内的 iPhone 13，128G，电池健康 85% 以上，不要维修过的，最好是同城个人卖家"
      />
      <el-button type="primary" plain :icon="MagicStick" :loading="state.generating" @click="generate">一句话生成</el-button>
    </div>

    <el-tabs v-model="state.tab">
      <el-tab-pane label="搜索条件" name="search">
        <el-form label-width="110px" :label-position="isMobile ? 'top' : 'right'">
          <el-form-item label="名称" required>
            <el-input v-model="state.form.name" maxlength="64" />
          </el-form-item>
          <el-form-item label="搜索关键词" required>
            <el-input-tag v-model="state.form.keywords" placeholder="输入后回车，最多 8 个" :max="8" save-on-blur />
            <div class="form-tip">每个关键词单独搜索一次，结果合并去重。</div>
          </el-form-item>
          <el-form-item label="价格区间">
            <div class="range">
              <el-input-number v-model="state.form.min_price" :min="0" :controls="false" placeholder="最低" :value-on-clear="null" />
              <span>-</span>
              <el-input-number v-model="state.form.max_price" :min="0" :controls="false" placeholder="最高" :value-on-clear="null" />
              <span class="muted">元</span>
            </div>
          </el-form-item>
          <el-form-item label="地区">
            <div class="range">
              <el-input v-model="state.form.province" placeholder="省份，如 广东" clearable class="w160" />
              <el-input v-model="state.form.city" placeholder="城市，如 深圳" clearable class="w160" />
            </div>
          </el-form-item>
          <el-form-item label="发布时间">
            <el-select v-model="state.form.publish_days" clearable placeholder="不限" class="w160">
              <el-option :value="1" label="1 天内" />
              <el-option :value="3" label="3 天内" />
              <el-option :value="7" label="7 天内" />
              <el-option :value="14" label="14 天内" />
              <el-option :value="30" label="30 天内" />
            </el-select>
          </el-form-item>
          <el-form-item label="排序">
            <el-radio-group v-model="state.form.sort">
              <el-radio-button value="newest">最新发布</el-radio-button>
              <el-radio-button value="price_asc">价格从低到高</el-radio-button>
              <el-radio-button value="default">综合</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="抓取页数">
            <el-input-number v-model="state.form.max_pages" :min="1" :max="5" />
            <div class="form-tip">每页约 30 条，页数越多越容易触发风控。</div>
          </el-form-item>
          <el-form-item label="筛选">
            <el-checkbox v-model="state.form.personal_only">只看个人闲置</el-checkbox>
            <el-checkbox v-model="state.form.free_shipping">只看包邮</el-checkbox>
          </el-form-item>
          <el-form-item label="搜索账号">
            <el-select v-model="state.form.account_id" clearable placeholder="匿名搜索（推荐）" class="w240">
              <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
            </el-select>
            <div class="form-tip">留空使用匿名会话搜索，避免主账号因频繁搜索被风控。</div>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="规则初筛" name="rules">
        <el-form label-width="130px" :label-position="isMobile ? 'top' : 'right'">
          <el-form-item label="标题包含任一">
            <el-input-tag v-model="state.form.rules.include_any" placeholder="回车添加，为空不限" save-on-blur />
          </el-form-item>
          <el-form-item label="标题必须全部包含">
            <el-input-tag v-model="state.form.rules.include_all" placeholder="回车添加" save-on-blur />
          </el-form-item>
          <el-form-item label="排除词">
            <el-input-tag v-model="state.form.rules.exclude" placeholder="标题或描述包含任一则排除，如：维修、配件、求购" save-on-blur />
          </el-form-item>
          <el-form-item label="发货地包含">
            <el-input-tag v-model="state.form.rules.areas" placeholder="如：深圳、广州，为空不限" save-on-blur />
          </el-form-item>
          <el-form-item label="二次价格过滤">
            <div class="range">
              <el-input-number v-model="state.form.rules.min_price" :min="0" :controls="false" placeholder="最低" :value-on-clear="null" />
              <span>-</span>
              <el-input-number v-model="state.form.rules.max_price" :min="0" :controls="false" placeholder="最高" :value-on-clear="null" />
            </div>
          </el-form-item>
          <el-form-item label="发布时间内（小时）">
            <el-input-number v-model="state.form.rules.max_age_hours" :min="1" placeholder="不限" :value-on-clear="null" />
          </el-form-item>
          <el-form-item label="最低芝麻信用">
            <el-select v-model="state.form.rules.min_seller_zhima" clearable placeholder="不限" class="w160">
              <el-option value="信用一般" label="信用一般" />
              <el-option value="信用良好" label="信用良好" />
              <el-option value="信用优秀" label="信用优秀" />
              <el-option value="信用极好" label="信用极好" />
            </el-select>
          </el-form-item>
          <el-form-item label="卖家注册天数 ≥">
            <el-input-number v-model="state.form.rules.min_seller_reg_days" :min="0" placeholder="不限" :value-on-clear="null" />
            <div class="form-tip">需开启「抓取卖家资料」才能生效。</div>
          </el-form-item>
          <el-form-item label="卖家黑名单">
            <el-input-tag v-model="state.form.rules.blacklist_sellers" placeholder="卖家昵称或 ID" save-on-blur />
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="AI 判定" name="ai">
        <el-form label-width="130px" :label-position="isMobile ? 'top' : 'right'">
          <el-form-item label="判定方式">
            <el-radio-group v-model="state.form.decision_mode">
              <el-radio-button value="ai">AI 判定</el-radio-button>
              <el-radio-button value="rule">仅规则</el-radio-button>
            </el-radio-group>
            <div class="form-tip">仅规则：通过初筛即推荐，不消耗大模型额度。</div>
          </el-form-item>
          <el-form-item label="判定标准">
            <el-input v-model="state.form.criteria" type="textarea" :rows="5" placeholder="用自然语言描述你的要求，例如：国行、无拆修、电池健康 ≥85%、屏幕无划痕；价格低于市场价 10% 以上才推荐" />
          </el-form-item>
          <el-form-item label="选项">
            <div class="checks">
              <el-checkbox v-model="state.form.ai_prescreen">AI 文本粗筛（先用便宜模型淘汰明显不符的）</el-checkbox>
              <el-checkbox v-model="state.form.analyze_images">分析商品图片</el-checkbox>
              <el-checkbox v-model="state.form.fetch_seller_profile">抓取卖家资料（更慢，风控风险更高）</el-checkbox>
            </div>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="定时与通知" name="schedule">
        <el-form label-width="130px" :label-position="isMobile ? 'top' : 'right'">
          <el-form-item label="自动搜索">
            <el-switch v-model="state.form.enabled" active-text="定时自动搜索" inactive-text="只手动搜索" />
          </el-form-item>
          <el-form-item v-if="state.form.enabled" label="搜索频率" required>
            <el-radio-group v-model="selectedCronPreset" class="cron-radio-list" @change="onCronPresetChange">
              <el-radio v-for="p in cronPresets" :key="p.value" :value="p.value" border class="cron-radio-item">
                {{ p.label }}
              </el-radio>
              <el-radio value="custom" border class="cron-radio-item">自定义 Cron 表达式</el-radio>
            </el-radio-group>
            <div v-if="selectedCronPreset === 'custom'" class="mt-s" style="width: 100%">
              <el-input v-model="state.form.cron" placeholder="例如：*/20 9-22 * * *" class="mono w240" />
              <div class="form-tip">标准 5 段 cron：分 时 日 月 周。间隔至少 5 分钟，建议 30 分钟以上。</div>
            </div>
          </el-form-item>
          <el-form-item label="通知有条件推荐">
            <el-switch v-model="state.form.notify_conditional" />
            <div class="form-tip">默认只推送「推荐」结果。想盯某件商品降价，请在结果卡片上点「价格监控」。</div>
          </el-form-item>
        </el-form>
      </el-tab-pane>
    </el-tabs>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="state.saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
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
@media (max-width: 768px) {
  .nl {
    flex-direction: column;
  }
}
</style>
