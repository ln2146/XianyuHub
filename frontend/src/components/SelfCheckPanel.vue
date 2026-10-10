<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Aim,
  CircleCheckFilled,
  CircleCloseFilled,
  Connection,
  Picture,
  RemoveFilled,
  Search,
  Tickets,
  User,
  VideoPlay,
  Warning,
  WarningFilled,
} from '@element-plus/icons-vue'
import { runSelfCheck, type SelfCheckItem, type SelfCheckResult } from '@/api/system'
import { useAccountsStore } from '@/stores/accounts'
import { fmtTime } from '@/utils/format'

/** 协议自检：少量只读请求确认闲鱼接口字段仍然正确（仅管理员可见） */
const accounts = useAccountsStore()

const form = reactive({ keyword: 'iphone', account_id: null as number | null })
const running = ref(false)
const result = ref<SelfCheckResult | null>(null)

/** 常用测试关键词预设 */
const presetKeywords = ['iphone', '显卡', 'switch', 'ps5', '拍立得']

onMounted(() => {
  accounts.load().catch(() => undefined)
})

function selectPresetKeyword(kw: string) {
  if (running.value) return
  form.keyword = kw
}

async function start() {
  const keyword = form.keyword.trim() || 'iphone'
  running.value = true
  try {
    result.value = await runSelfCheck({ keyword, account_id: form.account_id ?? null })
    if (result.value.ok) ElMessage.success('协议自检通过，所有接口与解析器工作正常')
    else ElMessage.warning('自检发现异常或字段缺失，请查看下方检测明细')
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
const pctColor = (pct: number) => (pct >= 80 ? 'var(--xh-primary)' : 'var(--xh-warning)')

const summary = computed(() => {
  const checks = result.value?.checks || []
  return {
    ok: checks.filter((c) => statusOf(c) === 'ok').length,
    fail: checks.filter((c) => statusOf(c) === 'fail').length,
    skipped: checks.filter((c) => statusOf(c) === 'skipped').length,
    ms: checks.reduce((n, c) => n + (c.ms || 0), 0),
  }
})

/** 未自检时的四大检验维度说明 */
const dimensions = [
  {
    icon: Search,
    title: '商品搜索与列表协议',
    endpoint: 'mtop.taobao.wireless.xianyu.search',
    fields: '标题、价格、地区、卖家昵称、主图、发布时间、想要人数',
    purpose: '保障选品雷达实时搜货、智能定时搜货与价格监控的抓取质量',
  },
  {
    icon: Picture,
    title: '商品详情与图文协议',
    endpoint: 'mtop.taobao.idle.item.detail',
    fields: '图文描述、成色规范、图片长图流、浏览量、卖家 ID、芝麻信用',
    purpose: '保障 AI 识图发品、商品详情抽取与商家资质核验准确度',
  },
  {
    icon: User,
    title: '账号身份与会话验活',
    endpoint: 'mtop.taobao.xianyu.user.info（需选择账号）',
    fields: 'Cookie 登录态、UNB 身份有效性、设备签名握手',
    purpose: '预防账号 Cookie 过期或风控引起的自动发货及消息回复异常',
  },
  {
    icon: Tickets,
    title: 'IM 通讯与订单链路',
    endpoint: 'mtop.taobao.idle.order.list / IM Token（需选择账号）',
    fields: 'IM AccessToken 令牌、在售商品、已售订单字段映射',
    purpose: '确保自动发货任务与客服自动回复全流程通信畅通',
  },
]
</script>

<template>
  <div class="selfcheck-container">
    <!-- 1. 监测说明横幅（精致卡片，替换之前生硬刺眼的蓝色大 alert） -->
    <div class="intro-card">
      <div class="intro-head">
        <div class="intro-icon-wrap">
          <el-icon><Aim /></el-icon>
        </div>
        <div class="intro-titles">
          <div class="intro-title">闲鱼接口协议与字段解析器自检</div>
          <div class="intro-subtitle">
            通过最小化轻量只读请求，实时探测闲鱼 App 核心接口端点与数据字段完整度，及时发现平台接口更新与风控限制。
          </div>
        </div>
      </div>

      <div class="intro-badges-row">
        <div class="intro-badge-item">
          <el-icon class="badge-icon"><Warning /></el-icon>
          <span>严格受风控限速保护，不影响主账号安全</span>
        </div>
        <div class="intro-badge-item">
          <el-icon class="badge-icon"><Tickets /></el-icon>
          <span>多维字段覆盖率探测，及时发现字段缺失</span>
        </div>
        <div class="intro-badge-item">
          <el-icon class="badge-icon"><Connection /></el-icon>
          <span>一旦检测到风控或滑动验证将立即熔断终止</span>
        </div>
      </div>
    </div>

    <!-- 2. 控制参数配置卡片 -->
    <div class="control-panel-card">
      <div class="control-row">
        <!-- 搜索关键词输入与预设 -->
        <div class="control-group">
          <label class="control-label">搜索关键词</label>
          <div class="input-with-presets">
            <el-input
              v-model="form.keyword"
              placeholder="例如：iphone"
              maxlength="40"
              clearable
              :prefix-icon="Search"
              class="keyword-input"
              :disabled="running"
              @keyup.enter="start"
            />
            <div class="preset-chips">
              <span class="preset-label">快捷预设：</span>
              <button
                v-for="kw in presetKeywords"
                :key="kw"
                type="button"
                class="preset-chip"
                :class="{ active: form.keyword === kw }"
                :disabled="running"
                @click="selectPresetKeyword(kw)"
              >
                {{ kw }}
              </button>
            </div>
          </div>
        </div>

        <!-- 检查账号选择 -->
        <div class="control-group">
          <label class="control-label">检查账号（选填）</label>
          <el-select
            v-model="form.account_id"
            clearable
            placeholder="不选择（仅匿名检查公开接口）"
            class="account-select"
            :disabled="running"
          >
            <el-option
              v-for="a in accounts.list"
              :key="a.id"
              :value="a.id"
              :label="a.remark || a.nickname || a.unb"
            >
              <div class="account-opt-row">
                <span>{{ a.remark || a.nickname || a.unb }}</span>
                <el-tag v-if="a.status === 'active'" size="small" type="success" effect="plain">正常</el-tag>
                <el-tag v-else size="small" type="info" effect="plain">{{ a.status }}</el-tag>
              </div>
            </el-option>
          </el-select>
        </div>

        <!-- 触发执行按钮 -->
        <div class="action-btn-wrap">
          <el-button
            type="primary"
            :icon="VideoPlay"
            :loading="running"
            class="start-check-btn"
            @click="start"
          >
            {{ running ? '正在自检中…' : '开始运行自检' }}
          </el-button>
        </div>
      </div>

      <!-- 运行中动态提示 -->
      <div v-if="running" class="running-status-bar">
        <el-icon class="spin-icon"><Connection /></el-icon>
        <span>正在依次模拟轻量协议请求进行字段覆盖率分析，通常需要 10~25 秒，请耐心等待…</span>
      </div>
    </div>

    <!-- 3. 自检结果展示区域 -->
    <template v-if="result">
      <!-- 汇总统计条 -->
      <div class="result-summary-card">
        <div class="summary-status-col">
          <div class="status-indicator-badge" :class="{ ok: result.ok, fail: !result.ok }">
            <el-icon v-if="result.ok"><CircleCheckFilled /></el-icon>
            <el-icon v-else><WarningFilled /></el-icon>
            <span>{{ result.ok ? '协议全链路正常 · 解析器健康' : '存在字段缺失或风控异常' }}</span>
          </div>
        </div>

        <div class="summary-stats-grid">
          <div class="stat-pill">
            <span class="stat-lbl">通过项</span>
            <span class="stat-val text-success">{{ summary.ok }} 项</span>
          </div>
          <div class="stat-pill">
            <span class="stat-lbl">失败项</span>
            <span class="stat-val" :class="summary.fail > 0 ? 'text-danger' : 'text-muted'">{{ summary.fail }} 项</span>
          </div>
          <div class="stat-pill">
            <span class="stat-lbl">跳过项</span>
            <span class="stat-val text-muted">{{ summary.skipped }} 项</span>
          </div>
          <div class="stat-pill">
            <span class="stat-lbl">检测耗时</span>
            <span class="stat-val mono">{{ (summary.ms / 1000).toFixed(1) }}s</span>
          </div>
          <div class="stat-pill">
            <span class="stat-lbl">执行时间</span>
            <span class="stat-val text-muted">{{ fmtTime(result.started_at, true) }}</span>
          </div>
        </div>
      </div>

      <!-- 检测明细项列表 -->
      <div class="checks-list">
        <div
          v-for="c in result.checks"
          :key="c.name"
          class="check-detail-card"
          :class="statusMeta[statusOf(c)].cls"
        >
          <div class="check-card-header">
            <div class="header-left">
              <el-icon :size="20" class="status-icon">
                <component :is="statusMeta[statusOf(c)].icon" />
              </el-icon>
              <span class="check-title">{{ c.title || c.name }}</span>
              <el-tag size="small" :type="statusMeta[statusOf(c)].tag" effect="plain">
                {{ statusMeta[statusOf(c)].label }}
              </el-tag>
            </div>
            <div class="header-right">
              <span class="latency-text mono">{{ c.skipped ? '-' : `${c.ms} ms` }}</span>
            </div>
          </div>

          <!-- 诊断说明文字 -->
          <div v-if="c.detail" class="check-detail-msg" :class="{ error: !c.ok && !c.skipped }">
            {{ c.detail }}
          </div>

          <!-- 字段覆盖率进度条矩阵 -->
          <div v-if="c.coverage && Object.keys(c.coverage).length" class="coverage-section">
            <div class="coverage-heading">
              <span>解析字段覆盖率探测</span>
              <span class="coverage-tip">（低于 80% 通常说明闲鱼接口字段重构，需要更新解析器）</span>
            </div>
            <div class="coverage-grid">
              <div v-for="r in coverageRows(c.coverage)" :key="r.field" class="cov-item-cell">
                <div class="cov-field-name" :class="{ warning: r.pct < 80 }">
                  <span>{{ r.field }}</span>
                  <span class="cov-pct-val mono">{{ r.pct }}%</span>
                </div>
                <el-progress
                  :percentage="r.pct"
                  :color="pctColor(r.pct)"
                  :stroke-width="6"
                  :show-text="false"
                  class="cov-progress"
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 4. 尚未运行自检时的自检维度指引卡片（填补空白，提升专业度） -->
    <div v-else-if="!running" class="precheck-guide-wrapper">
      <div class="precheck-heading">
        <span class="heading-title">自检维度与协议覆盖范围</span>
        <span class="heading-hint">点击上方「开始运行自检」即可实时探测以下四类协议与数据字段</span>
      </div>

      <div class="dimensions-grid">
        <div v-for="dim in dimensions" :key="dim.title" class="dimension-card">
          <div class="dim-icon-row">
            <div class="dim-icon-box">
              <el-icon><component :is="dim.icon" /></el-icon>
            </div>
            <div class="dim-titles">
              <div class="dim-title">{{ dim.title }}</div>
              <div class="dim-endpoint mono">{{ dim.endpoint }}</div>
            </div>
            <el-tag size="small" type="info" effect="plain" class="dim-tag">待自检</el-tag>
          </div>

          <div class="dim-content">
            <div class="dim-row">
              <span class="dim-lbl">覆盖字段：</span>
              <span class="dim-val">{{ dim.fields }}</span>
            </div>
            <div class="dim-row">
              <span class="dim-lbl">核心作用：</span>
              <span class="dim-val text-muted">{{ dim.purpose }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.selfcheck-container {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-4);
}

/* ================= 1. 说明横幅 ================= */
.intro-card {
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: var(--xh-space-4);
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-3);
}

.intro-head {
  display: flex;
  align-items: flex-start;
  gap: var(--xh-space-3);
}

.intro-icon-wrap {
  width: 38px;
  height: 38px;
  border-radius: var(--xh-radius-sm);
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--xh-fs-xl);
  flex-shrink: 0;
}

.intro-titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.intro-title {
  font-size: var(--xh-fs-md);
  font-weight: 600;
  color: var(--xh-text);
}

.intro-subtitle {
  font-size: var(--xh-fs-sm);
  color: var(--xh-text-2);
  line-height: 1.5;
}

.intro-badges-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--xh-space-2) var(--xh-space-4);
  padding-top: var(--xh-space-2);
  border-top: 1px solid var(--xh-border);
}

.intro-badge-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--xh-fs-xs);
  color: var(--xh-text-2);
}

.badge-icon {
  color: var(--xh-primary);
  font-size: var(--xh-fs-sm);
}

/* ================= 2. 控制参数卡片 ================= */
.control-panel-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: var(--xh-space-4);
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-3);
}

.control-row {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: var(--xh-space-3) var(--xh-space-4);
}

.control-group {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-1);
}

.control-label {
  font-size: var(--xh-fs-xs);
  font-weight: 500;
  color: var(--xh-text-2);
}

.input-with-presets {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.keyword-input {
  width: 220px;
}

.preset-chips {
  display: flex;
  align-items: center;
  gap: 4px;
}

.preset-label {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}

.preset-chip {
  padding: 1px 7px;
  border-radius: var(--xh-radius-pill);
  font-size: 11px;
  border: 1px solid var(--xh-border);
  background: var(--xh-fill);
  color: var(--xh-text-2);
  cursor: pointer;
  transition: all 0.15s ease;
}

.preset-chip:hover {
  border-color: var(--xh-primary-border);
  color: var(--xh-primary);
}

.preset-chip.active {
  background: var(--xh-primary-soft);
  border-color: var(--xh-primary-border);
  color: var(--xh-primary);
  font-weight: 500;
}

.account-select {
  width: 240px;
}

.account-opt-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.action-btn-wrap {
  margin-left: auto;
}

.start-check-btn {
  height: 36px;
  padding: 0 var(--xh-space-4);
}

.running-status-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: var(--xh-space-2) var(--xh-space-3);
  border-radius: var(--xh-radius-sm);
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
  font-size: var(--xh-fs-xs);
  margin-top: var(--xh-space-1);
}

.spin-icon {
  animation: spin 1.2s infinite linear;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* ================= 3. 结果汇总与指标条 ================= */
.result-summary-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: var(--xh-space-3) var(--xh-space-4);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--xh-space-3);
}

.status-indicator-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: var(--xh-radius-pill);
  font-size: var(--xh-fs-sm);
  font-weight: 600;
}

.status-indicator-badge.ok {
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
  border: 1px solid var(--xh-primary-border);
}

.status-indicator-badge.fail {
  background: #fff1f0;
  color: var(--xh-danger);
  border: 1px solid #ffa39e;
}

.summary-stats-grid {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--xh-space-3) var(--xh-space-4);
}

.stat-pill {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.stat-lbl {
  font-size: 11px;
  color: var(--xh-muted);
}

.stat-val {
  font-size: var(--xh-fs-sm);
  font-weight: 600;
}

.text-success { color: var(--xh-primary); }
.text-danger { color: var(--xh-danger); }
.text-muted { color: var(--xh-text-2); }

/* ================= 4. 检测项目卡片 ================= */
.checks-list {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-3);
}

.check-detail-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: var(--xh-space-3) var(--xh-space-4);
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-2);
  transition: box-shadow 0.15s ease;
}

.check-detail-card:hover {
  box-shadow: var(--xh-shadow-1);
}

.check-detail-card.ok {
  border-left: 3px solid var(--xh-primary);
}

.check-detail-card.fail {
  border-left: 3px solid var(--xh-danger);
}

.check-detail-card.skipped {
  border-left: 3px solid var(--xh-muted);
}

.check-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
}

.status-icon {
  flex-shrink: 0;
}

.check-detail-card.ok .status-icon { color: var(--xh-primary); }
.check-detail-card.fail .status-icon { color: var(--xh-danger); }
.check-detail-card.skipped .status-icon { color: var(--xh-muted); }

.check-title {
  font-size: var(--xh-fs-md);
  font-weight: 600;
  color: var(--xh-text);
}

.latency-text {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}

.check-detail-msg {
  font-size: var(--xh-fs-sm);
  color: var(--xh-text-2);
  line-height: 1.5;
  padding-left: 28px;
}

.check-detail-msg.error {
  color: var(--xh-danger);
  font-weight: 500;
}

.coverage-section {
  padding-left: 28px;
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-2);
  margin-top: 4px;
}

.coverage-heading {
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
  font-size: var(--xh-fs-xs);
  font-weight: 600;
  color: var(--xh-text);
}

.coverage-tip {
  font-size: 11px;
  font-weight: normal;
  color: var(--xh-muted);
}

.coverage-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--xh-space-2) var(--xh-space-4);
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-sm);
  padding: var(--xh-space-2) var(--xh-space-3);
}

.cov-item-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.cov-field-name {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--xh-fs-xs);
  color: var(--xh-text-2);
}

.cov-field-name.warning {
  color: var(--xh-warning);
  font-weight: 600;
}

.cov-pct-val {
  font-size: 11px;
}

/* ================= 5. 待自检时的维度指引卡片 ================= */
.precheck-guide-wrapper {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-3);
}

.precheck-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--xh-space-2);
  padding: 0 2px;
}

.heading-title {
  font-size: var(--xh-fs-md);
  font-weight: 600;
  color: var(--xh-text);
}

.heading-hint {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}

.dimensions-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--xh-space-3);
}

@media (max-width: 800px) {
  .dimensions-grid {
    grid-template-columns: 1fr;
  }
}

.dimension-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: var(--xh-space-4);
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-3);
  box-shadow: var(--xh-shadow-1);
}

.dim-icon-row {
  display: flex;
  align-items: center;
  gap: var(--xh-space-3);
}

.dim-icon-box {
  width: 36px;
  height: 36px;
  border-radius: var(--xh-radius-sm);
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--xh-fs-lg);
  flex-shrink: 0;
}

.dim-titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.dim-title {
  font-size: var(--xh-fs-sm);
  font-weight: 600;
  color: var(--xh-text);
}

.dim-endpoint {
  font-size: 11px;
  color: var(--xh-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dim-tag {
  flex-shrink: 0;
}

.dim-content {
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-sm);
  padding: var(--xh-space-2) var(--xh-space-3);
}

.dim-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: var(--xh-fs-xs);
  line-height: 1.45;
}

.dim-lbl {
  color: var(--xh-muted);
  flex-shrink: 0;
}

.dim-val {
  color: var(--xh-text-2);
}
</style>
