<script setup lang="ts">
// 商品分析 + 商家分析（IP 属地 × 评价动态）+ AI 综合点评
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { CopyDocument, MagicStick, Refresh, WarningFilled } from '@element-plus/icons-vue'
import {
  getItemInsight,
  itemAnalysis,
  itemInsight,
  sellerAnalysis,
  type InsightOut,
  type ItemAnalysis,
  type SellerAnalysis,
} from '@/api/buyer'
import EChart from '@/components/EChart.vue'
import { askSellerOnGoofish, copyText, fmtMoney, fmtRelative, fmtTime, itemUrl } from '@/utils/format'

// 模块级会话内存缓存，退出抽屉或切页面后，同个会话内点进同一商品瞬间 0ms 恢复
const sessionInsightCache = new Map<
  string,
  { ai: InsightOut; seller?: SellerAnalysis | null; time?: string | null }
>()

const props = withDefaults(
  defineProps<{
    itemId: string
    taskId?: number | null
    keyword?: string | null
    accountId?: number | null
    /** 详情接口已拿到的 IP 属地 / 已售件数，卖家主页未返回时兜底 */
    ipLocation?: string
    soldCnt?: number | null
    initialTab?: 'item' | 'seller' | 'ai'
  }>(),
  { initialTab: 'item' },
)

type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'

const tab = ref(props.initialTab)
const item = reactive({ loading: false, error: '', data: null as ItemAnalysis | null })
const seller = reactive({ loading: false, error: '', data: null as SellerAnalysis | null })
const ai = reactive({ loading: false, error: '', data: null as InsightOut | null })
const aiAnalyzedAt = ref<string | null>(null)

// 优先检查内存缓存，有则立即可用
const cached = sessionInsightCache.get(props.itemId)
if (cached) {
  ai.data = cached.ai
  if (cached.seller && !seller.data) seller.data = cached.seller
  if (cached.time) aiAnalyzedAt.value = cached.time
}

function errText(e: unknown, fallback: string) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || fallback
}

async function loadItem() {
  item.loading = true
  item.error = ''
  try {
    const res = await itemAnalysis(props.itemId, {
      task_id: props.taskId,
      keyword: props.keyword,
      account_id: props.accountId,
    })
    item.data = res
    // 如果后台已持久化了该商品的 AI 点评历史记录，立即恢复
    if (res.ai_insight && !ai.data) {
      ai.data = res.ai_insight
      if (res.ai_insight_at) aiAnalyzedAt.value = res.ai_insight_at
      sessionInsightCache.set(props.itemId, {
        ai: res.ai_insight,
        time: res.ai_insight_at,
      })
    }
  } catch (e) {
    item.error = errText(e, '商品分析失败')
  } finally {
    item.loading = false
  }
}

async function loadSeller(refresh = false) {
  seller.loading = true
  seller.error = ''
  try {
    seller.data = await sellerAnalysis(props.itemId, {
      account_id: props.accountId,
      refresh,
      ip_location: props.ipLocation,
      sold_cnt: props.soldCnt,
    })
  } catch (e) {
    seller.error = errText(e, '商家分析失败')
  } finally {
    seller.loading = false
  }
}

async function loadAi() {
  ai.loading = true
  ai.error = ''
  try {
    const res = await itemInsight(props.itemId, {
      task_id: props.taskId,
      keyword: props.keyword,
      account_id: props.accountId,
      ip_location: props.ipLocation,
      sold_cnt: props.soldCnt,
    })
    ai.data = res.ai
    aiAnalyzedAt.value = new Date().toISOString()
    item.data = res.item
    if (res.seller) seller.data = res.seller
    sessionInsightCache.set(props.itemId, {
      ai: res.ai,
      seller: res.seller,
      time: aiAnalyzedAt.value,
    })
  } catch (e) {
    ai.error = errText(e, 'AI 点评失败')
  } finally {
    ai.loading = false
  }
}

// 卖家主页需要 4 次接口调用（受风控限速），切到该页签时才加载
// 切到 AI 页签时，若尚未加载到已有的记录，尝试拉取已保存的点评
watch(
  tab,
  async (t) => {
    if (t === 'seller' && !seller.data && !seller.loading) loadSeller()
    if (t === 'ai' && !ai.data && !ai.loading) {
      try {
        const saved = await getItemInsight(props.itemId)
        if (saved?.ai) {
          ai.data = saved.ai
          if (saved.seller && !seller.data) seller.data = saved.seller
          if (saved.item?.ai_insight_at) aiAnalyzedAt.value = saved.item.ai_insight_at
          sessionInsightCache.set(props.itemId, {
            ai: saved.ai,
            seller: saved.seller,
            time: aiAnalyzedAt.value,
          })
        }
      } catch {
        /* 静默忽略未分析情况 */
      }
    }
  },
  { immediate: true },
)
onMounted(loadItem)

// ---------------------------------------------------------------- 展示辅助
const pct = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined ? '-' : `${(v * 100).toFixed(digits)}%`
const signedPct = (v: number | null | undefined) =>
  v === null || v === undefined ? '-' : `${v > 0 ? '+' : ''}${(v * 100).toFixed(0)}%`

function scoreColor(score: number) {
  if (score >= 80) return '#1e9e6a'
  if (score >= 65) return '#409eff'
  if (score >= 45) return '#e6a23c'
  return '#e5484d'
}

const itemLevelType = computed<TagType>(() => {
  const s = item.data?.score ?? 0
  return s >= 75 ? 'success' : s >= 60 ? 'primary' : s >= 40 ? 'warning' : 'danger'
})

const sellerLevelType = computed<TagType>(() => {
  const l = seller.data?.level
  return l === '可信' ? 'success' : l === '一般' ? 'primary' : l === '谨慎' ? 'warning' : 'danger'
})

const ipMatchMap: Record<SellerAnalysis['ip_match'], { label: string; type: TagType }> = {
  match: { label: '属地一致', type: 'success' },
  mismatch: { label: '属地不一致', type: 'warning' },
  overseas: { label: '非大陆 IP', type: 'danger' },
  unknown: { label: '无法比对', type: 'info' },
}

const sellerTypeMap: Record<SellerAnalysis['seller_type'], { label: string; type: TagType }> = {
  personal: { label: '个人玩家', type: 'success' },
  dealer: { label: '疑似贩子 / 商家', type: 'warning' },
  unknown: { label: '身份未知', type: 'info' },
}

const trendMap: Record<string, { label: string; type: TagType }> = {
  up: { label: '口碑上升', type: 'success' },
  down: { label: '口碑下滑', type: 'danger' },
  stable: { label: '口碑平稳', type: 'info' },
  unknown: { label: '数据不足', type: 'info' },
}

const trustMap: Record<InsightOut['trust_level'], { label: string; type: TagType }> = {
  high: { label: '可信度高', type: 'success' },
  medium: { label: '可信度一般', type: 'warning' },
  low: { label: '可信度低', type: 'danger' },
}

const sourceLabel: Record<ItemAnalysis['sample_source'], string> = {
  task: '该智能搜索近 30 天样本',
  keyword: '关键词匹配的市场商品库',
  none: '无样本',
}

/** 价格在 min ~ max 之间的位置（0~100），用于价格带标尺 */
const pricePos = computed(() => {
  const d = item.data
  if (!d?.market || !d.price || d.market.max <= d.market.min) return null
  const { min, max, p25, median, p75 } = d.market
  const pos = (v: number) => Math.max(0, Math.min(100, ((v - min) / (max - min)) * 100))
  return { me: pos(d.price), p25: pos(p25), median: pos(median), p75: pos(p75) }
})

// 评价动态：按月堆叠柱（好评 / 中评 / 差评）
const ratingOption = computed(() => {
  const m = seller.data?.ratings.monthly || []
  const series = [
    { name: '好评', key: 'positive', color: '#1e9e6a' },
    { name: '中评', key: 'neutral', color: '#9aa1ad' },
    { name: '差评', key: 'negative', color: '#e5484d' },
  ] as const
  return {
    grid: { left: 32, right: 8, top: 28, bottom: 24 },
    legend: { top: 0, right: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: '#606266', fontSize: 12 } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: {
      type: 'category',
      data: m.map((b) => b.month),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#dcdfe6' } },
      axisLabel: { color: '#8a919f', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: '#f0f2f5' } },
      axisLabel: { color: '#8a919f', fontSize: 11 },
    },
    series: series.map((s) => ({
      name: s.name,
      type: 'bar',
      stack: 'rate',
      barMaxWidth: 18,
      data: m.map((b) => b[s.key]),
      itemStyle: { color: s.color, borderColor: '#fff', borderWidth: 1 },
    })),
  }
})

function rateTag(rate: number | null): { label: string; type: TagType } {
  if (rate === 1) return { label: '好评', type: 'success' }
  if (rate === 0) return { label: '中评', type: 'info' }
  if (rate !== null && rate < 0) return { label: '差评', type: 'danger' }
  return { label: '未评级', type: 'info' }
}
</script>

<template>
  <div class="analysis">
    <el-tabs v-model="tab" class="tabs">
      <!-- ============================== 商品分析 -->
      <el-tab-pane label="商品分析" name="item">
        <div v-loading="item.loading" class="pane">
          <el-alert v-if="item.error" type="error" :title="item.error" show-icon :closable="false" />
          <template v-if="item.data">
            <div class="score-head">
              <el-progress type="dashboard" :width="86" :stroke-width="7" :percentage="item.data.score" :color="scoreColor(item.data.score)">
                <template #default>
                  <div class="score-num">{{ item.data.score }}</div>
                  <div class="score-unit">综合分</div>
                </template>
              </el-progress>
              <div class="score-meta">
                <div>
                  <el-tag :type="itemLevelType" effect="dark">{{ item.data.level }}</el-tag>
                  <el-tag class="ml" effect="plain">{{ item.data.deal_label }}</el-tag>
                  <el-tag v-if="item.data.suspicious_low" class="ml" type="danger" effect="plain">异常低价</el-tag>
                </div>
                <div class="muted small">
                  价格样本：{{ sourceLabel[item.data.sample_source] }}
                  <template v-if="item.data.market"> · {{ item.data.market.count }} 个</template>
                </div>
              </div>
            </div>

            <!-- 价格带标尺 -->
            <div v-if="pricePos && item.data.market" class="block">
              <div class="block-title">市场价位置</div>
              <div class="ruler">
                <div class="band" :style="{ left: `${pricePos.p25}%`, width: `${pricePos.p75 - pricePos.p25}%` }" />
                <div class="tick" :style="{ left: `${pricePos.median}%` }" />
                <div class="me" :style="{ left: `${pricePos.me}%` }">
                  <span class="me-label">{{ fmtMoney(item.data.price) }}</span>
                </div>
              </div>
              <div class="ruler-legend muted small">
                <span>最低 {{ fmtMoney(item.data.market.min) }}</span>
                <span>P25 {{ fmtMoney(item.data.market.p25) }} · 中位 {{ fmtMoney(item.data.market.median) }} · P75 {{ fmtMoney(item.data.market.p75) }}</span>
                <span>最高 {{ fmtMoney(item.data.market.max) }}</span>
              </div>
            </div>

            <div class="metrics">
              <div class="metric">
                <div class="m-label">较中位数</div>
                <div class="m-val" :class="{ good: (item.data.diff_to_median ?? 0) < 0, bad: (item.data.diff_to_median ?? 0) > 0.1 }">
                  {{ signedPct(item.data.diff_to_median) }}
                </div>
              </div>
              <div class="metric">
                <div class="m-label">价格分位</div>
                <div class="m-val">{{ item.data.percentile === null ? '-' : `P${item.data.percentile}` }}</div>
              </div>
              <div class="metric">
                <div class="m-label">相对原价</div>
                <div class="m-val">{{ item.data.discount === null ? '-' : `${(item.data.discount * 10).toFixed(1)} 折` }}</div>
              </div>
              <div class="metric">
                <div class="m-label">价格变化</div>
                <div class="m-val" :class="{ good: (item.data.price_change ?? 0) < 0 }">{{ signedPct(item.data.price_change) }}</div>
              </div>
              <div class="metric">
                <div class="m-label">热度</div>
                <div class="m-val">{{ item.data.heat_level }}</div>
              </div>
              <div class="metric">
                <div class="m-label">想要 / 天</div>
                <div class="m-val">{{ item.data.want_per_day ?? '-' }}</div>
              </div>
              <div class="metric">
                <div class="m-label">浏览转想要</div>
                <div class="m-val">{{ pct(item.data.want_rate, 1) }}</div>
              </div>
              <div class="metric">
                <div class="m-label">挂牌天数</div>
                <div class="m-val">{{ item.data.age_days ?? '-' }}</div>
              </div>
              <div class="metric">
                <div class="m-label">图片 / 描述</div>
                <div class="m-val">{{ item.data.image_count }} 张 / {{ item.data.desc_len }} 字</div>
              </div>
            </div>

            <div v-if="item.data.missing_info.length" class="block">
              <div class="block-title">描述未提及（建议向卖家确认）</div>
              <div class="chips">
                <el-tag v-for="m in item.data.missing_info" :key="m" size="small" type="warning" effect="plain">{{ m }}</el-tag>
              </div>
            </div>
            <div class="pros-cons">
              <div v-if="item.data.highlights.length" class="pros">
                <div class="block-title">亮点</div>
                <ul><li v-for="h in item.data.highlights" :key="h">{{ h }}</li></ul>
              </div>
              <div v-if="item.data.risks.length" class="cons">
                <div class="block-title">风险</div>
                <ul><li v-for="r in item.data.risks" :key="r">{{ r }}</li></ul>
              </div>
            </div>
          </template>
        </div>
      </el-tab-pane>

      <!-- ============================== 商家分析 -->
      <el-tab-pane label="商家分析" name="seller">
        <div v-loading="seller.loading" element-loading-text="正在读取卖家主页与评价…" class="pane">
          <el-alert v-if="seller.error" type="error" :title="seller.error" show-icon :closable="false">
            <el-button size="small" class="mt" @click="loadSeller()">重试</el-button>
          </el-alert>
          <template v-if="seller.data">
            <div class="score-head">
              <el-progress type="dashboard" :width="86" :stroke-width="7" :percentage="seller.data.score" :color="scoreColor(seller.data.score)">
                <template #default>
                  <div class="score-num">{{ seller.data.score }}</div>
                  <div class="score-unit">可信分</div>
                </template>
              </el-progress>
              <div class="score-meta">
                <div class="seller-name">
                  <el-avatar v-if="seller.data.avatar" :size="22" :src="seller.data.avatar" />
                  <b>{{ seller.data.nick || '闲鱼卖家' }}</b>
                </div>
                <div>
                  <el-tag :type="sellerLevelType" effect="dark">{{ seller.data.level }}</el-tag>
                  <el-tag class="ml" :type="sellerTypeMap[seller.data.seller_type].type" effect="plain">
                    {{ sellerTypeMap[seller.data.seller_type].label }}
                  </el-tag>
                </div>
                <div class="muted small">
                  <template v-if="seller.data.zhima">芝麻{{ seller.data.zhima }} · </template>
                  <template v-if="seller.data.reg_days !== null">注册 {{ seller.data.reg_days }} 天 · </template>
                  <template v-if="seller.data.item_cnt !== null">商品 {{ seller.data.item_cnt }} · </template>
                  评价 {{ seller.data.rate_cnt ?? '-' }}
                  <el-button link size="small" :icon="Refresh" class="ml" title="忽略 24 小时缓存重新拉取" @click="loadSeller(true)">
                    {{ seller.data.fetched_at ? `${fmtRelative(seller.data.fetched_at)}更新` : '刷新' }}
                  </el-button>
                </div>
              </div>
            </div>

            <!-- IP 属地 -->
            <div class="block ip-block" :class="seller.data.ip_match">
              <div class="block-title">
                IP 属地 × 发货地
                <el-tag size="small" class="ml" :type="ipMatchMap[seller.data.ip_match].type">{{ ipMatchMap[seller.data.ip_match].label }}</el-tag>
              </div>
              <div class="ip-row">
                <div class="ip-cell">
                  <div class="m-label">IP 属地</div>
                  <div class="m-val">{{ seller.data.ip_location || '未获取' }}</div>
                </div>
                <div class="ip-arrow">⇄</div>
                <div class="ip-cell">
                  <div class="m-label">发货地</div>
                  <div class="m-val">{{ seller.data.item_area || '未标注' }}</div>
                </div>
              </div>
              <div class="small ip-note">{{ seller.data.ip_note }}</div>
            </div>

            <!-- 评价动态 -->
            <div class="block">
              <div class="block-title">
                评价动态
                <el-tag size="small" class="ml" :type="trendMap[seller.data.ratings.trend]?.type">{{ trendMap[seller.data.ratings.trend]?.label }}</el-tag>
                <el-tag v-if="seller.data.ratings.burst" size="small" class="ml" type="danger">集中评价</el-tag>
              </div>
              <div class="metrics">
                <div class="metric">
                  <div class="m-label">卖家好评率</div>
                  <div class="m-val">{{ pct(seller.data.ratings.positive_rate) }}</div>
                </div>
                <div class="metric">
                  <div class="m-label">近 90 天 / 此前</div>
                  <div class="m-val">{{ pct(seller.data.ratings.recent_positive_rate) }} / {{ pct(seller.data.ratings.earlier_positive_rate) }}</div>
                </div>
                <div class="metric">
                  <div class="m-label">近 30 天新增</div>
                  <div class="m-val">{{ seller.data.ratings.recent_30d }} 条</div>
                </div>
                <div class="metric">
                  <div class="m-label">好 / 中 / 差</div>
                  <div class="m-val">{{ seller.data.ratings.positive }} / {{ seller.data.ratings.neutral }} / {{ seller.data.ratings.negative }}</div>
                </div>
                <div class="metric">
                  <div class="m-label">最近评价</div>
                  <div class="m-val">{{ fmtRelative(seller.data.ratings.last_rated_at) || '-' }}</div>
                </div>
                <div class="metric">
                  <div class="m-label">分析样本</div>
                  <div class="m-val">
                    {{ seller.data.ratings.as_seller }} 条<span v-if="seller.data.ratings.as_seller > seller.data.ratings.rated" class="m-sub">（{{ seller.data.ratings.as_seller - seller.data.ratings.rated }} 条买家未评价）</span>
                  </div>
                </div>
              </div>
              <div v-if="seller.data.ratings.burst_note" class="small warn-line">
                <el-icon><WarningFilled /></el-icon>
                <span>{{ seller.data.ratings.burst_note }}，存在刷评或批量出货可能</span>
              </div>
              <EChart v-if="seller.data.ratings.monthly.length >= 2" :option="ratingOption" height="170px" />
              <div v-if="seller.data.ratings.negative_hits.length || seller.data.ratings.positive_hits.length" class="chips mt">
                <el-tag v-for="[w, n] in seller.data.ratings.negative_hits" :key="`n${w}`" size="small" type="danger" effect="light">{{ w }} ×{{ n }}</el-tag>
                <el-tag v-for="[w, n] in seller.data.ratings.positive_hits" :key="`p${w}`" size="small" type="success" effect="light">{{ w }} ×{{ n }}</el-tag>
              </div>
            </div>

            <div v-if="seller.data.ratings.negatives.length" class="block">
              <div class="block-title">中差评 / 负面评价</div>
              <div v-for="(r, i) in seller.data.ratings.negatives" :key="i" class="review bad">
                <div class="review-head">
                  <el-tag size="small" :type="rateTag(r.rate).type" effect="plain">{{ rateTag(r.rate).label }}</el-tag>
                  <span class="muted small">{{ r.created_at ? fmtTime(r.created_at).slice(0, 10) : '' }}</span>
                </div>
                <div class="review-text">{{ r.content || '（无文字）' }}</div>
              </div>
            </div>

            <div v-if="seller.data.ratings.recent.length" class="block">
              <div class="block-title">最新评价</div>
              <div v-for="(r, i) in seller.data.ratings.recent" :key="i" class="review">
                <div class="review-head">
                  <el-tag size="small" :type="rateTag(r.rate).type" effect="plain">{{ rateTag(r.rate).label }}</el-tag>
                  <span class="muted small">{{ r.role }} · {{ r.created_at ? fmtTime(r.created_at).slice(0, 10) : '' }}</span>
                </div>
                <div class="review-text">{{ r.content }}</div>
              </div>
            </div>

            <div class="block">
              <div class="block-title">在售商品画像</div>
              <div class="muted small">
                在售 {{ seller.data.on_sale_sampled }} · 已售 {{ seller.data.sold_sampled }}（主页节选）· 标题相似度 {{ seller.data.homogeneity.toFixed(2) }}
              </div>
              <ul v-if="seller.data.type_reasons.length" class="plain-list">
                <li v-for="r in seller.data.type_reasons" :key="r">{{ r }}</li>
              </ul>
              <div v-if="seller.data.introduction" class="intro small">简介：{{ seller.data.introduction }}</div>
            </div>

            <div class="pros-cons">
              <div v-if="seller.data.highlights.length" class="pros">
                <div class="block-title">加分项</div>
                <ul><li v-for="h in seller.data.highlights" :key="h">{{ h }}</li></ul>
              </div>
              <div v-if="seller.data.risks.length" class="cons">
                <div class="block-title">风险点</div>
                <ul><li v-for="r in seller.data.risks" :key="r">{{ r }}</li></ul>
              </div>
            </div>
          </template>
        </div>
      </el-tab-pane>

      <!-- ============================== AI 综合点评 -->
      <el-tab-pane name="ai">
        <template #label>
          <span class="tab-label-item">
            <span>AI 点评</span>
            <span v-if="ai.data" class="tab-analyzed-dot" title="已保留分析记录"></span>
          </span>
        </template>
        <div v-loading="ai.loading" element-loading-text="AI 正在结合商品与商家数据分析…" class="pane">
          <el-alert v-if="ai.error" type="error" :title="ai.error" show-icon :closable="false" class="mb" />
          <div v-if="!ai.data" class="ai-empty">
            <p class="muted small">综合商品价格位置、卖家 IP 属地与评价动态，生成一份购买参考。会读取卖家主页（已缓存则不重复请求）并消耗一次大模型调用。</p>
            <el-button type="primary" :icon="MagicStick" :loading="ai.loading" @click="loadAi">生成 AI 点评</el-button>
          </div>
          <template v-else>
            <div class="ai-head">
              <div class="ai-head-tags">
                <el-tag :type="trustMap[ai.data.trust_level].type" effect="dark">{{ trustMap[ai.data.trust_level].label }}</el-tag>
                <el-tag :type="sellerTypeMap[ai.data.seller_type].type" effect="plain">{{ sellerTypeMap[ai.data.seller_type].label }}</el-tag>
                <span v-if="aiAnalyzedAt" class="muted small ai-time">分析于 {{ fmtRelative(aiAnalyzedAt) || fmtTime(aiAnalyzedAt).slice(0, 16) }}</span>
                <el-tag v-else size="small" type="success" effect="light">已保留分析记录</el-tag>
              </div>
              <el-button link size="small" :icon="Refresh" :loading="ai.loading" @click="loadAi">重新分析</el-button>
            </div>
            <div class="advice">{{ ai.data.advice }}</div>
            <dl class="ai-list">
              <dt>商品</dt><dd>{{ ai.data.item_summary }}</dd>
              <dt>商家</dt><dd>{{ ai.data.seller_summary }}</dd>
              <dt>IP 属地</dt><dd>{{ ai.data.ip_assessment }}</dd>
              <dt>评价动态</dt><dd>{{ ai.data.comment_insight }}</dd>
            </dl>
            <div v-if="ai.data.questions_for_seller.length" class="block">
              <div class="block-title q-head">
                可以问卖家
                <span>
                  <el-button link size="small" :icon="CopyDocument" @click="copyText(ai.data.questions_for_seller.join('\n'))">复制全部</el-button>
                  <el-button link size="small" type="primary" @click="askSellerOnGoofish(ai.data.questions_for_seller, itemUrl(itemId))">去闲鱼问卖家</el-button>
                </span>
              </div>
              <div v-for="q in ai.data.questions_for_seller" :key="q" class="q" title="点击复制" @click="copyText(q)">{{ q }}</div>
            </div>
          </template>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.analysis {
  font-size: 13px;
}
.tabs :deep(.el-tabs__header) {
  margin-bottom: 10px;
}
.pane {
  min-height: 160px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ml {
  margin-left: 6px;
}
.mt {
  margin-top: 8px;
}
.mb {
  margin-bottom: 8px;
}
.score-head {
  display: flex;
  align-items: center;
  gap: 14px;
}
.score-num {
  font-size: 22px;
  font-weight: 700;
  color: var(--xh-text, #1f2329);
  line-height: 1.1;
}
.score-unit {
  font-size: 11px;
  color: var(--xh-muted, #8a919f);
}
.score-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.seller-name {
  display: flex;
  align-items: center;
  gap: 6px;
}
.block {
  border: 1px solid var(--xh-border, #ebeef5);
  border-radius: 8px;
  padding: 10px 12px;
}
.block-title {
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
}
.metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
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
  color: var(--xh-text, #1f2329);
  margin-top: 2px;
}
.m-sub {
  font-size: var(--xh-fs-xs);
  font-weight: 400;
  color: var(--xh-muted);
}
.m-val.good {
  color: #1e9e6a;
}
.m-val.bad {
  color: #e5484d;
}
/* 价格带标尺 */
.ruler {
  position: relative;
  height: 8px;
  margin: 26px 6px 6px;
  background: #eef0f3;
  border-radius: 4px;
}
.band {
  position: absolute;
  top: 0;
  bottom: 0;
  background: rgba(30, 158, 106, 0.25);
  border-radius: 4px;
}
.tick {
  position: absolute;
  top: -3px;
  width: 2px;
  height: 14px;
  background: #606266;
  transform: translateX(-1px);
}
.me {
  position: absolute;
  top: -4px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #e5484d;
  border: 2px solid #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
  transform: translateX(-8px);
}
.me-label {
  position: absolute;
  bottom: 18px;
  left: 50%;
  transform: translateX(-50%);
  white-space: nowrap;
  font-size: 12px;
  font-weight: 700;
  color: #e5484d;
}
.ruler-legend {
  display: flex;
  justify-content: space-between;
  gap: 6px;
  flex-wrap: wrap;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.pros-cons {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.pros-cons ul,
.plain-list {
  margin: 0;
  padding-left: 18px;
  line-height: 1.6;
}
.pros {
  background: #f0f9f4;
  border-radius: 8px;
  padding: 10px 12px;
}
.cons {
  background: #fef3f2;
  border-radius: 8px;
  padding: 10px 12px;
}
.pros:only-child,
.cons:only-child {
  grid-column: 1 / -1;
}
.ip-block.match {
  border-color: rgba(30, 158, 106, 0.35);
}
.ip-block.mismatch {
  border-color: rgba(230, 162, 60, 0.5);
}
.ip-block.overseas {
  border-color: rgba(229, 72, 77, 0.5);
}
.ip-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ip-cell {
  flex: 1;
  background: #f7f8fa;
  border-radius: 6px;
  padding: 6px 10px;
}
.ip-arrow {
  color: var(--xh-muted, #8a919f);
}
.ip-note {
  margin-top: 6px;
  color: #606266;
}
.warn-line {
  color: var(--xh-warning-text);
  margin: 6px 0;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.review {
  padding: 6px 0;
  border-bottom: 1px dashed #ebeef5;
}
.review:last-child {
  border-bottom: none;
}
.review-head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.review-text {
  margin-top: 4px;
  line-height: 1.5;
  color: #303133;
}
.intro {
  margin-top: 6px;
  color: #606266;
}
.ai-empty {
  text-align: center;
  padding: 20px 8px;
}
.tab-label-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.tab-analyzed-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--el-color-success, #67c23a);
}
.ai-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}
.ai-head-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.ai-time {
  font-size: 11px;
}
.advice {
  font-size: 14px;
  font-weight: 600;
  background: #f0f9f4;
  border-left: 3px solid #1e9e6a;
  padding: 8px 10px;
  border-radius: 4px;
}
.ai-list {
  margin: 0;
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 8px 10px;
  line-height: 1.6;
}
.ai-list dt {
  font-weight: 600;
  color: #606266;
}
.ai-list dd {
  margin: 0;
}
.q-head {
  justify-content: space-between;
}
.q {
  padding: 6px 8px;
  margin-top: 4px;
  background: var(--el-color-primary-light-9);
  border-radius: 6px;
  cursor: pointer;
}
.q:hover {
  background: var(--el-color-primary-light-8);
}
@media (max-width: 640px) {
  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .pros-cons {
    grid-template-columns: 1fr;
  }
}
</style>
