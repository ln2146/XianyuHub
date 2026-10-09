<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleCheckFilled, CircleCloseFilled, RemoveFilled, VideoPlay } from '@element-plus/icons-vue'
import { runSelfCheck, type SelfCheckItem, type SelfCheckResult } from '@/api/system'
import { useAccountsStore } from '@/stores/accounts'
import { useMobile } from '@/composables/useMobile'
import { fmtTime } from '@/utils/format'

/** 协议自检：少量只读请求确认闲鱼接口字段仍然正确（仅管理员可见） */
const accounts = useAccountsStore()
const isMobile = useMobile()

const form = reactive({ keyword: 'iphone', account_id: null as number | null })
const running = ref(false)
const result = ref<SelfCheckResult | null>(null)

onMounted(() => {
  accounts.load().catch(() => undefined)
})

async function start() {
  const keyword = form.keyword.trim() || 'iphone'
  running.value = true
  try {
    result.value = await runSelfCheck({ keyword, account_id: form.account_id ?? null })
    if (result.value.ok) ElMessage.success('自检通过')
    else ElMessage.warning('自检发现异常，请查看下方详情')
  } catch {
    /* 拦截器已提示 */
  } finally {
    running.value = false
  }
}

type Status = 'ok' | 'fail' | 'skipped'
const statusOf = (c: SelfCheckItem): Status => (c.skipped ? 'skipped' : c.ok ? 'ok' : 'fail')
const statusMeta: Record<Status, { label: string; icon: typeof CircleCheckFilled; cls: string; tag: 'success' | 'danger' | 'info' }> = {
  ok: { label: '通过', icon: CircleCheckFilled, cls: 'ok', tag: 'success' },
  fail: { label: '失败', icon: CircleCloseFilled, cls: 'fail', tag: 'danger' },
  skipped: { label: '跳过', icon: RemoveFilled, cls: 'skipped', tag: 'info' },
}

/** 覆盖率转为百分比：后端返回 0~1 比例；若出现 >1 的值则视为已是百分比 */
function coverageRows(cov: Record<string, number>) {
  const values = Object.values(cov)
  const isRatio = values.every((v) => v <= 1)
  return Object.entries(cov).map(([field, v]) => {
    const pct = Math.max(0, Math.min(100, Math.round((isRatio ? v * 100 : v) * 10) / 10))
    return { field, pct }
  })
}
const pctColor = (pct: number) => (pct >= 80 ? 'var(--el-color-success)' : 'var(--el-color-warning)')

const summary = computed(() => {
  const checks = result.value?.checks || []
  return {
    ok: checks.filter((c) => statusOf(c) === 'ok').length,
    fail: checks.filter((c) => statusOf(c) === 'fail').length,
    skipped: checks.filter((c) => statusOf(c) === 'skipped').length,
    ms: checks.reduce((n, c) => n + (c.ms || 0), 0),
  }
})
</script>

<template>
  <div class="selfcheck">
    <el-alert type="info" :closable="false" show-icon class="intro">
      <template #title>
        自检只发送少量只读请求（匿名搜索 1 页、商品详情 1 次；选择账号时额外检查登录态、IM 令牌、我的商品、已售订单），受风控限速保护，用于确认接口字段是否仍然正确。
      </template>
      <div class="small">字段覆盖率明显下降通常意味着闲鱼调整了接口结构，需要更新解析器；一旦触发风控会立即停止后续检查。</div>
    </el-alert>

    <el-form :inline="!isMobile" :label-position="isMobile ? 'top' : 'right'" class="form" @submit.prevent="start">
      <el-form-item label="搜索关键词">
        <el-input v-model="form.keyword" placeholder="iphone" maxlength="40" clearable class="w180" :disabled="running" />
      </el-form-item>
      <el-form-item label="检查账号">
        <el-select v-model="form.account_id" clearable placeholder="不选择（仅匿名检查）" class="w220" :disabled="running">
          <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :icon="VideoPlay" :loading="running" native-type="submit">{{ running ? '自检中…' : '开始自检' }}</el-button>
      </el-form-item>
    </el-form>
    <div v-if="running" class="muted small running-tip">正在依次检查，通常需要 10~30 秒，请勿重复点击…</div>

    <template v-if="result">
      <div class="summary">
        <el-tag :type="result.ok ? 'success' : 'danger'" effect="dark">{{ result.ok ? '全部正常' : '存在异常' }}</el-tag>
        <span class="small">通过 {{ summary.ok }} · 失败 {{ summary.fail }} · 跳过 {{ summary.skipped }}</span>
        <span class="small muted">耗时 {{ (summary.ms / 1000).toFixed(1) }}s · 开始于 {{ fmtTime(result.started_at, true) }}</span>
      </div>

      <div class="checks">
        <div v-for="c in result.checks" :key="c.name" class="check" :class="statusMeta[statusOf(c)].cls">
          <div class="check-head">
            <el-icon :size="20" class="st-icon"><component :is="statusMeta[statusOf(c)].icon" /></el-icon>
            <span class="check-title">{{ c.title || c.name }}</span>
            <el-tag size="small" :type="statusMeta[statusOf(c)].tag" effect="plain">{{ statusMeta[statusOf(c)].label }}</el-tag>
            <span class="ms muted small">{{ c.skipped ? '-' : `${c.ms} ms` }}</span>
          </div>
          <div v-if="c.detail" class="detail small">{{ c.detail }}</div>
          <div v-if="c.coverage && Object.keys(c.coverage).length" class="coverage">
            <div class="small muted cov-label">字段覆盖率</div>
            <div class="cov-grid">
              <div v-for="r in coverageRows(c.coverage)" :key="r.field" class="cov-row">
                <span class="cov-field small" :class="{ low: r.pct < 80 }">{{ r.field }}</span>
                <el-progress :percentage="r.pct" :color="pctColor(r.pct)" :stroke-width="8" class="cov-bar" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
    <el-empty v-else-if="!running" description="尚未运行自检" :image-size="60" />
  </div>
</template>

<style scoped>
.intro {
  margin-bottom: 16px;
}
.form {
  margin-bottom: 4px;
}
.w180 {
  width: 180px;
}
.w220 {
  width: 220px;
}
.running-tip {
  margin-bottom: 12px;
}
.summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin: 8px 0 14px;
}
.checks {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.check {
  border: 1px solid var(--el-border-color-lighter);
  border-left: 4px solid var(--el-color-info-light-5);
  border-radius: 6px;
  padding: 10px 14px;
}
.check.ok {
  border-left-color: var(--el-color-success);
}
.check.fail {
  border-left-color: var(--el-color-danger);
}
.check-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.st-icon {
  flex-shrink: 0;
}
.check.ok .st-icon {
  color: var(--el-color-success);
}
.check.fail .st-icon {
  color: var(--el-color-danger);
}
.check.skipped .st-icon {
  color: var(--el-color-info);
}
.check-title {
  font-weight: 600;
}
.ms {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}
.detail {
  margin: 6px 0 0 28px;
  color: var(--el-text-color-regular);
  word-break: break-all;
}
.check.fail .detail {
  color: var(--el-color-danger);
}
.coverage {
  margin: 8px 0 0 28px;
}
.cov-label {
  margin-bottom: 4px;
}
.cov-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 4px 24px;
}
.cov-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cov-field {
  width: 70px;
  flex-shrink: 0;
}
.cov-field.low {
  color: var(--el-color-warning);
  font-weight: 600;
}
.cov-bar {
  flex: 1;
  min-width: 0;
}
@media (max-width: 768px) {
  .w180,
  .w220 {
    width: 100%;
  }
  .detail,
  .coverage {
    margin-left: 0;
  }
}
</style>
