<script setup lang="ts">
// 卖家视角的买家分析：该不该卖给他、要防什么（到手刀 / 仅退款 / 调包 / 站外交易…）
import { computed, onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, EditPen, MagicStick, Refresh } from '@element-plus/icons-vue'
import { addBlacklist, buyerRiskAnalysis, buyerRiskInsight, type BuyerAnalysis, type BuyerInsight } from '@/api/order'
import { copyText, fmtMoney, fmtRelative } from '@/utils/format'

const props = defineProps<{ convId?: number | null; orderPk?: number | null }>()
const emit = defineEmits<{ (e: 'use-reply', text: string): void }>()

type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'

const state = reactive({ loading: false, error: '', data: null as BuyerAnalysis | null })
const ai = reactive({ loading: false, error: '', data: null as BuyerInsight | null })
const target = () => ({ conv_id: props.convId ?? undefined, order_pk: props.orderPk ?? undefined })

function errText(e: unknown, fallback: string) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || fallback
}

async function load(refresh = false) {
  state.loading = true
  state.error = ''
  try {
    state.data = await buyerRiskAnalysis({ ...target(), refresh })
  } catch (e) {
    state.error = errText(e, '买家分析失败')
  } finally {
    state.loading = false
  }
}

async function loadAi() {
  ai.loading = true
  ai.error = ''
  try {
    const res = await buyerRiskInsight(target())
    ai.data = res.ai
    state.data = res.analysis
  } catch (e) {
    ai.error = errText(e, 'AI 研判失败')
  } finally {
    ai.loading = false
  }
}

async function block() {
  const d = state.data
  if (!d) return
  const defaultReason = d.risks[0]?.slice(0, 60) || '买家风险'
  try {
    const { value } = await ElMessageBox.prompt('拉黑后该买家的订单不会自动发货，需要人工处理。', `拉黑 ${d.nick || d.buyer_id}`, {
      inputValue: defaultReason,
      inputPlaceholder: '拉黑原因',
      confirmButtonText: '拉黑',
      cancelButtonText: '取消',
    })
    await addBlacklist(d.buyer_id, (value || defaultReason).slice(0, 200))
    ElMessage.success('已加入黑名单')
    await load()
  } catch {
    /* 取消或拦截器已提示 */
  }
}

onMounted(() => load())

const verdictMap: Record<BuyerAnalysis['verdict'], { label: string; type: TagType; color: string }> = {
  sell: { label: '可以卖', type: 'success', color: '#1e9e6a' },
  caution: { label: '谨慎交易', type: 'warning', color: '#e6a23c' },
  decline: { label: '建议不卖', type: 'danger', color: '#e5484d' },
}
const scoreColor = computed(() => (state.data ? verdictMap[state.data.verdict].color : '#909399'))
</script>

<template>
  <div v-loading="state.loading" element-loading-text="正在读取买家主页、聊天与交易记录…" class="buyer-risk">
    <el-alert v-if="state.error" type="error" :title="state.error" show-icon :closable="false">
      <el-button size="small" class="mt" @click="load()">重试</el-button>
    </el-alert>

    <template v-if="state.data">
      <div class="head">
        <el-progress type="dashboard" :width="88" :stroke-width="7" :percentage="state.data.score" :color="scoreColor">
          <template #default>
            <div class="score-num">{{ state.data.score }}</div>
            <div class="score-unit">安全分</div>
          </template>
        </el-progress>
        <div class="head-meta">
          <div class="name">
            <el-avatar v-if="state.data.avatar" :size="22" :src="state.data.avatar" />
            <b>{{ state.data.nick || state.data.buyer_id }}</b>
          </div>
          <div>
            <el-tag :type="verdictMap[state.data.verdict].type" effect="dark">{{ state.data.level }}</el-tag>
            <el-tag v-if="state.data.buyer_credit" class="ml" effect="plain">{{ state.data.buyer_credit }}</el-tag>
            <el-tag v-if="state.data.history.blacklisted" class="ml" type="danger" effect="plain">黑名单</el-tag>
          </div>
          <div class="muted small">
            被卖家评价 {{ state.data.as_buyer }} 次 · 本店订单 {{ state.data.history.orders }} 笔
            <el-button link size="small" :icon="Refresh" class="ml" title="忽略 24 小时缓存，重新读取买家主页" @click="load(true)">
              {{ fmtRelative(state.data.analyzed_at) }}分析
            </el-button>
          </div>
        </div>
      </div>

      <div class="actions">
        <el-button type="primary" :icon="MagicStick" :loading="ai.loading" @click="loadAi">AI 研判</el-button>
        <el-button v-if="!state.data.history.blacklisted" type="danger" plain @click="block">拉黑该买家</el-button>
      </div>

      <!-- AI 研判 -->
      <el-alert v-if="ai.error" type="error" :title="ai.error" show-icon :closable="false" />
      <div v-if="ai.data" class="block ai">
        <div class="block-title">
          AI 研判
          <el-tag size="small" class="ml" :type="verdictMap[ai.data.verdict].type">{{ verdictMap[ai.data.verdict].label }}</el-tag>
        </div>
        <p class="ai-summary">{{ ai.data.summary }}</p>
        <p class="muted small">聊天：{{ ai.data.chat_assessment }}</p>
        <ul v-if="ai.data.risk_points.length" class="plain-list">
          <li v-for="r in ai.data.risk_points" :key="r">{{ r }}</li>
        </ul>
        <div v-if="ai.data.suggested_reply" class="reply">
          <div class="reply-text">{{ ai.data.suggested_reply }}</div>
          <div class="reply-ops">
            <el-button link size="small" :icon="CopyDocument" @click="copyText(ai.data.suggested_reply)">复制</el-button>
            <el-button link size="small" type="primary" :icon="EditPen" @click="emit('use-reply', ai.data.suggested_reply)">填入回复框</el-button>
          </div>
        </div>
      </div>

      <div v-if="state.data.risks.length" class="block cons">
        <div class="block-title">风险点</div>
        <ul class="plain-list">
          <li v-for="r in state.data.risks" :key="r">{{ r }}</li>
        </ul>
      </div>
      <div v-if="state.data.highlights.length" class="block pros">
        <div class="block-title">加分项</div>
        <ul class="plain-list">
          <li v-for="h in state.data.highlights" :key="h">{{ h }}</li>
        </ul>
      </div>
      <div v-if="state.data.precautions.length || ai.data?.precautions.length" class="block">
        <div class="block-title">防范建议</div>
        <ul class="plain-list">
          <li v-for="t in [...new Set([...state.data.precautions, ...(ai.data?.precautions || [])])]" :key="t">{{ t }}</li>
        </ul>
      </div>

      <!-- 聊天信号 -->
      <div class="block">
        <div class="block-title">聊天中的风险话术</div>
        <div v-if="!state.data.chat_signals.length" class="muted small">没有发现先发货、收到再付、不满意就退、加微信、差评威胁等话术</div>
        <div v-for="s in state.data.chat_signals" :key="s.key" class="signal">
          <el-tag size="small" type="warning" effect="plain">{{ s.label }}</el-tag>
          <span v-for="e in s.evidence" :key="e" class="quote">“{{ e }}”</span>
        </div>
        <div v-if="state.data.bargain_rounds" class="muted small mt">已议价 {{ state.data.bargain_rounds }} 轮</div>
      </div>

      <!-- 卖家给他的评价 -->
      <div class="block">
        <div class="block-title">其他卖家对他的评价</div>
        <div v-if="state.data.profile_error" class="muted small">未能读取买家主页：{{ state.data.profile_error }}</div>
        <template v-else>
          <div class="muted small">
            共 {{ state.data.as_buyer }} 条（主页节选），好评 {{ state.data.as_buyer_positive }}，中差评 {{ state.data.as_buyer_negative }}
          </div>
          <div v-if="state.data.negative_hits.length || state.data.positive_hits.length" class="chips mt">
            <el-tag v-for="[w, n] in state.data.negative_hits" :key="`n${w}`" size="small" type="danger" effect="light">{{ w }} ×{{ n }}</el-tag>
            <el-tag v-for="[w, n] in state.data.positive_hits" :key="`p${w}`" size="small" type="success" effect="light">{{ w }} ×{{ n }}</el-tag>
          </div>
          <div v-for="(r, i) in state.data.negative_reviews" :key="i" class="review">
            <el-tag size="small" :type="r.rate === -1 ? 'danger' : r.rate === 0 ? 'info' : 'warning'" effect="plain">
              {{ r.rate === -1 ? '差评' : r.rate === 0 ? '中评' : '好评含负面词' }}
            </el-tag>
            <span class="review-text">{{ r.content || '（无文字）' }}</span>
          </div>
        </template>
      </div>

      <div class="block">
        <div class="block-title">与本店的交易</div>
        <div class="metrics">
          <div class="metric"><div class="m-label">订单</div><div class="m-val">{{ state.data.history.orders }}</div></div>
          <div class="metric"><div class="m-label">已完成</div><div class="m-val">{{ state.data.history.completed }}</div></div>
          <div class="metric">
            <div class="m-label">退款</div>
            <div class="m-val" :class="{ bad: state.data.history.refunded }">{{ state.data.history.refunded }}</div>
          </div>
          <div class="metric"><div class="m-label">成交额</div><div class="m-val">{{ fmtMoney(state.data.history.total_amount) }}</div></div>
        </div>
        <div v-if="state.data.history.blacklisted" class="small bad mt">黑名单原因：{{ state.data.history.blacklist_reason || '未填写' }}</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.buyer-risk {
  min-height: 200px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  font-size: 13px;
}
.ml {
  margin-left: 6px;
}
.mt {
  margin-top: 6px;
}
.head {
  display: flex;
  align-items: center;
  gap: 14px;
}
.score-num {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--xh-text, #1f2329);
}
.score-unit {
  font-size: 11px;
  color: var(--xh-muted, #8a919f);
}
.head-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.name {
  display: flex;
  align-items: center;
  gap: 6px;
}
.actions {
  display: flex;
  gap: 8px;
}
.block {
  border: 1px solid var(--xh-border, #ebeef5);
  border-radius: 8px;
  padding: 10px 12px;
}
.block-title {
  display: flex;
  align-items: center;
  font-weight: 600;
  color: #303133;
  margin-bottom: 6px;
}
.pros {
  background: #f0f9f4;
  border-color: transparent;
}
.cons {
  background: #fef3f2;
  border-color: transparent;
}
.ai {
  border-color: rgba(64, 158, 255, 0.35);
}
.ai-summary {
  margin: 0 0 4px;
  font-weight: 600;
  line-height: 1.6;
}
.plain-list {
  margin: 0;
  padding-left: 18px;
  line-height: 1.7;
}
.reply {
  margin-top: 8px;
  background: var(--el-color-primary-light-9);
  border-radius: 6px;
  padding: 8px 10px;
}
.reply-text {
  line-height: 1.6;
}
.reply-ops {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}
.signal {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
}
.quote {
  color: #606266;
  background: #f7f8fa;
  border-radius: 4px;
  padding: 1px 6px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.review {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 6px 0;
  border-bottom: 1px dashed #ebeef5;
}
.review:last-child {
  border-bottom: none;
}
.review-text {
  line-height: 1.5;
}
.metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}
.metric {
  background: #f7f8fa;
  border-radius: 6px;
  padding: 6px 8px;
}
.m-label {
  font-size: 11.5px;
  color: var(--xh-muted, #8a919f);
}
.m-val {
  font-weight: 600;
  margin-top: 2px;
}
.bad {
  color: #e5484d;
}
@media (max-width: 640px) {
  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
