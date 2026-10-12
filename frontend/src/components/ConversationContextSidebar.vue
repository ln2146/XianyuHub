<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Box,
  Close,
  CopyDocument,
  CreditCard,
  Edit,
  Goods,
  Promotion,
  Right,
  TopRight,
  UserFilled,
} from '@element-plus/icons-vue'
import {
  getConversationContext,
  type ConversationContext,
} from '@/api/message'
import { updateItem } from '@/api/goods'
import BuyerRiskPanel from '@/components/BuyerRiskPanel.vue'
import { copyText, fmtMoney, fmtTime, itemUrl } from '@/utils/format'

const props = defineProps<{
  convId: number | null
  peerName?: string
}>()

const emit = defineEmits<{
  (e: 'use-reply', text: string): void
  (e: 'close'): void
}>()

const router = useRouter()
const loading = ref(false)
const context = ref<ConversationContext | null>(null)
const activeTab = ref<'item' | 'orders' | 'risk'>('item')

// 底价快捷修改
const isEditingFloor = ref(false)
const inputFloorPrice = ref<number | null>(null)
const floorSaving = ref(false)

async function load() {
  if (!props.convId) {
    context.value = null
    return
  }
  loading.value = true
  isEditingFloor.value = false
  try {
    const res = await getConversationContext(props.convId)
    context.value = res
    inputFloorPrice.value = res.item?.floor_price ?? null
  } catch (err: any) {
    // 拦截器通常会处理异常
  } finally {
    loading.value = false
  }
}

watch(
  () => props.convId,
  () => {
    load()
  },
  { immediate: true },
)

function startEditFloor() {
  inputFloorPrice.value = context.value?.item?.floor_price ?? null
  isEditingFloor.value = true
}

async function saveFloor() {
  const it = context.value?.item
  if (!it || !it.id) {
    ElMessage.warning('该商品尚未同步至本地商品库，请先前往商品管理同步')
    return
  }
  const val = inputFloorPrice.value !== null && inputFloorPrice.value !== undefined ? Number(inputFloorPrice.value) : null
  if (val !== null && it.price !== null && it.price !== undefined && val > it.price) {
    ElMessage.warning('底价不能高于售价')
    return
  }

  floorSaving.value = true
  try {
    await updateItem(it.id, { floor_price: val })
    it.floor_price = val
    isEditingFloor.value = false
    ElMessage.success('底价已成功更新并生效于 AI 议价策略')
    // 重新加载一次上下文以刷新智能话术
    if (props.convId) {
      const fresh = await getConversationContext(props.convId)
      context.value = fresh
    }
  } catch {
    /* 拦截器已处理 */
  } finally {
    floorSaving.value = false
  }
}

function useReply(text: string) {
  emit('use-reply', text)
  ElMessage.success('已填入输入框')
}

function goToOrder(orderId: string) {
  router.push({ path: '/orders/list', query: { q: orderId } })
}

const statusTagType = (st: string) => {
  if (st === 'paid' || st === 'delivered' || st === 'completed') return 'success'
  if (st === 'refunding' || st === 'refunded' || st === 'fail_reason' || st === 'deliver_failed') return 'danger'
  if (st === 'delivering' || st === 'risk_hold' || st === 'manual') return 'warning'
  return 'info'
}
</script>

<template>
  <aside class="context-sidebar" v-loading="loading">
    <!-- 顶栏：Tab 切换与收起按钮 -->
    <div class="sidebar-header">
      <div class="sidebar-tabs">
        <button
          type="button"
          class="tab-btn"
          :class="{ active: activeTab === 'item' }"
          @click="activeTab = 'item'"
        >
          <el-icon><Goods /></el-icon>
          <span>咨询商品</span>
        </button>

        <button
          type="button"
          class="tab-btn"
          :class="{ active: activeTab === 'orders' }"
          @click="activeTab = 'orders'"
        >
          <el-icon><Box /></el-icon>
          <span>关联订单</span>
          <span v-if="context?.orders.length" class="order-badge">{{ context.orders.length }}</span>
        </button>

        <button
          type="button"
          class="tab-btn"
          :class="{ active: activeTab === 'risk' }"
          @click="activeTab = 'risk'"
        >
          <el-icon><UserFilled /></el-icon>
          <span>买家画像</span>
        </button>
      </div>

      <button type="button" class="close-btn" title="收起侧边栏" @click="emit('close')">
        <el-icon><Close /></el-icon>
      </button>
    </div>

    <!-- 侧边栏内容区 -->
    <div class="sidebar-body">
      <!-- ==================== Tab 1: 咨询商品 ==================== -->
      <div v-show="activeTab === 'item'" class="tab-content">
        <template v-if="context?.item">
          <!-- 商品卡片卡头 -->
          <div class="item-card">
            <div class="item-cover-wrap">
              <el-image
                v-if="context.item.image_url"
                :src="context.item.image_url"
                fit="cover"
                class="item-cover"
                :preview-src-list="[context.item.image_url]"
                preview-teleported
              />
              <div v-else class="item-cover-empty">
                <el-icon><Goods /></el-icon>
              </div>
            </div>

            <div class="item-main-info">
              <div class="item-title-row">
                <a
                  :href="itemUrl(context.item.item_id)"
                  target="_blank"
                  rel="noopener"
                  class="item-title ellipsis-2"
                  :title="context.item.title"
                >
                  {{ context.item.title }}
                </a>
              </div>

              <div class="item-id-row">
                <span class="id-text mono">ID: {{ context.item.item_id }}</span>
                <el-button link size="small" :icon="CopyDocument" @click="copyText(context.item.item_id)">复制</el-button>
              </div>

              <div class="item-bottom-row">
                <div class="item-stats-chips">
                  <span v-if="context.item.status" class="stat-chip status-chip" :class="context.item.status">
                    {{ context.item.status === 'on_sale' ? '在售中' : context.item.status === 'sold' ? '已售出' : '已下架' }}
                  </span>
                  <span v-if="context.item.want_cnt !== null && context.item.want_cnt !== undefined" class="stat-chip">
                    {{ context.item.want_cnt }} 想要
                  </span>
                  <span v-if="context.item.browse_cnt !== null && context.item.browse_cnt !== undefined" class="stat-chip">
                    {{ context.item.browse_cnt }} 浏览
                  </span>
                </div>
                <a :href="itemUrl(context.item.item_id)" target="_blank" rel="noopener" class="jump-link">
                  <span>闲鱼直达</span>
                  <el-icon><TopRight /></el-icon>
                </a>
              </div>
            </div>
          </div>

          <!-- 核心：标价 vs 底价安全矩阵 -->
          <div class="price-matrix-card">
            <div class="matrix-grid">
              <div class="matrix-cell">
                <span class="m-label">挂牌标价</span>
                <span class="m-val price-text mono">
                  {{ context.item.price !== null && context.item.price !== undefined ? fmtMoney(context.item.price) : '未设置' }}
                </span>
              </div>

              <div class="matrix-cell floor-cell">
                <div class="m-label-row">
                  <span class="m-label">保底售价 (AI底线)</span>
                  <el-button
                    v-if="!isEditingFloor && context.item.id"
                    link
                    type="primary"
                    size="small"
                    class="edit-floor-btn"
                    :icon="Edit"
                    @click="startEditFloor"
                  >
                    修改
                  </el-button>
                </div>

                <div v-if="!isEditingFloor" class="floor-display-wrap">
                  <span v-if="context.item.floor_price !== null && context.item.floor_price !== undefined" class="m-val floor-val mono">
                    {{ fmtMoney(context.item.floor_price) }}
                  </span>
                  <span v-else class="floor-unset-tip">未设底价（AI 不议价）</span>
                </div>

                <!-- 就地快速编辑底价 -->
                <div v-else class="floor-edit-box">
                  <el-input-number
                    v-model="inputFloorPrice"
                    :min="0"
                    :max="context.item.price || 999999"
                    :precision="0"
                    size="small"
                    controls-position="right"
                    placeholder="输入底价"
                    class="floor-input"
                  />
                  <div class="floor-edit-actions">
                    <el-button size="small" type="primary" :loading="floorSaving" @click="saveFloor">保存</el-button>
                    <el-button size="small" @click="isEditingFloor = false">取消</el-button>
                  </div>
                </div>
              </div>
            </div>

            <div v-if="context.item.floor_price && context.item.price && context.item.floor_price < context.item.price" class="profit-bar">
              <span class="profit-label">最大议价空间：</span>
              <span class="profit-val mono">¥{{ (context.item.price - context.item.floor_price).toFixed(0) }}</span>
              <span class="profit-sub">（最多 {{ context.item.max_rounds || 3 }} 轮阶梯让步）</span>
            </div>
          </div>

          <!-- 自动发货卡密绑定状态 -->
          <div v-if="context.item.binding_info" class="binding-card">
            <div class="bc-head">
              <div class="bc-title">
                <el-icon class="bc-icon"><CreditCard /></el-icon>
                <span>已绑定自动发货</span>
              </div>
              <el-tag size="small" type="success" effect="plain">
                {{ context.item.binding_info.kind === 'pool' ? '卡密库存' : context.item.binding_info.kind === 'text' ? '固定文案' : '动态API' }}
              </el-tag>
            </div>
            <div class="bc-body">
              <div class="bc-pool-name ellipsis">{{ context.item.binding_info.pool_name }}</div>
              <div v-if="context.item.binding_info.kind === 'pool'" class="bc-stock-row">
                <span class="stock-label">可用库存：</span>
                <span
                  class="stock-val mono"
                  :class="context.item.binding_info.available_stock <= context.item.binding_info.low_stock_threshold ? 'low-stock' : ''"
                >
                  {{ context.item.binding_info.available_stock }} 张
                </span>
                <span v-if="context.item.binding_info.available_stock <= context.item.binding_info.low_stock_threshold" class="stock-warn">
                  (余量不足)
                </span>
              </div>
            </div>
          </div>

          <!-- 快捷智能话术 -->
          <div class="quick-phrases-card">
            <div class="qp-head">
              <div class="qp-title">
                <el-icon><Promotion /></el-icon>
                <span>议价与促单建议（点击填入）</span>
              </div>
            </div>

            <div class="phrases-list">
              <div
                v-for="(p, idx) in context.quick_replies"
                :key="idx"
                class="phrase-item"
                @click="useReply(p.text)"
              >
                <div class="phrase-tag" :class="`tag-${idx % 4}`">{{ p.tag }}</div>
                <div class="phrase-text">{{ p.text }}</div>
              </div>
            </div>
          </div>
        </template>

        <template v-else>
          <div class="no-item-box">
            <el-icon class="no-item-icon"><Goods /></el-icon>
            <div class="no-item-title">未识别到关联商品</div>
            <div class="no-item-sub">买家可能从个人主页直接发起对话，或本账号尚未同步商品库。</div>
          </div>

          <!-- 兜底通用快捷话术 -->
          <div v-if="context?.quick_replies.length" class="quick-phrases-card mt-m">
            <div class="qp-head">
              <div class="qp-title">
                <el-icon><Promotion /></el-icon>
                <span>常用回复短语（点击填入）</span>
              </div>
            </div>
            <div class="phrases-list">
              <div
                v-for="(p, idx) in context.quick_replies"
                :key="idx"
                class="phrase-item"
                @click="useReply(p.text)"
              >
                <div class="phrase-tag" :class="`tag-${idx % 4}`">{{ p.tag }}</div>
                <div class="phrase-text">{{ p.text }}</div>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- ==================== Tab 2: 关联订单 ==================== -->
      <div v-show="activeTab === 'orders'" class="tab-content">
        <template v-if="context?.orders.length">
          <div class="orders-list">
            <div v-for="ord in context.orders" :key="ord.id" class="order-card">
              <div class="oc-header">
                <el-tag size="small" :type="statusTagType(ord.status)" effect="light">
                  {{ ord.status_label }}
                </el-tag>
                <span class="oc-amount mono">{{ ord.amount !== null && ord.amount !== undefined ? fmtMoney(ord.amount) : '¥0' }}</span>
              </div>

              <div class="oc-title ellipsis-2">{{ ord.item_title }}</div>

              <div class="oc-meta-row">
                <span class="oc-id mono">单号: {{ ord.order_id }}</span>
                <el-button link size="small" :icon="CopyDocument" @click="copyText(ord.order_id)">复制</el-button>
              </div>

              <div v-if="ord.paid_at" class="oc-time-row">
                <span class="oc-label">平台付款通知：</span>
                <span class="oc-val">{{ fmtTime(ord.paid_at) }}</span>
              </div>

              <div v-if="ord.delivered_at" class="oc-time-row">
                <span class="oc-label">发货时间：</span>
                <span class="oc-val">{{ fmtTime(ord.delivered_at) }}</span>
              </div>

              <div v-if="ord.delivery_preview" class="oc-delivery-preview">
                <div class="dp-label">发货内容摘要：</div>
                <div class="dp-content mono">{{ ord.delivery_preview }}</div>
              </div>

              <div class="oc-actions">
                <el-button size="small" type="primary" plain :icon="Right" @click="goToOrder(ord.order_id)">
                  订单管理详情
                </el-button>
              </div>
            </div>
          </div>
        </template>

        <template v-else>
          <div class="no-order-box">
            <el-icon class="no-order-icon"><Box /></el-icon>
            <div class="no-order-title">买家尚未下单</div>
            <div class="no-order-sub">当前该会话未产生关联付款订单，可通过左侧聊天引导买家尽快拍下付款。</div>
          </div>
        </template>
      </div>

      <!-- ==================== Tab 3: 买家画像 ==================== -->
      <div v-show="activeTab === 'risk'" class="tab-content risk-tab">
        <BuyerRiskPanel v-if="convId" :conv-id="convId" @use-reply="useReply" />
      </div>
    </div>
  </aside>
</template>

<style scoped>
.context-sidebar {
  width: 330px;
  flex-shrink: 0;
  border-left: 1px solid var(--xh-border);
  background: #ffffff;
  display: flex;
  flex-direction: column;
  height: 100%;
  box-sizing: border-box;
  animation: slideInRight 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
}

@keyframes slideInRight {
  from {
    transform: translateX(12px);
    opacity: 0.6;
  }
  to {
    transform: translateX(0);
    opacity: 1;
  }
}

/* 顶栏与标签 */
.sidebar-header {
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 10px;
  border-bottom: 1px solid var(--xh-border);
  background: #fafbfc;
  flex-shrink: 0;
}

.sidebar-tabs {
  display: flex;
  gap: 4px;
  background: #eef2f6;
  padding: 3px;
  border-radius: 8px;
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  border: none;
  background: transparent;
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 500;
  color: #64748b;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tab-btn:hover {
  color: #0f172a;
}

.tab-btn.active {
  background: #ffffff;
  color: var(--xh-primary, #059669);
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.order-badge {
  background: var(--xh-primary, #059669);
  color: #fff;
  font-size: 10px;
  line-height: 14px;
  height: 14px;
  min-width: 14px;
  padding: 0 3px;
  border-radius: 10px;
  text-align: center;
  font-weight: 700;
}

.close-btn {
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  padding: 6px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s ease;
}

.close-btn:hover {
  background: #e2e8f0;
  color: #0f172a;
}

/* 内容滚动区 */
.sidebar-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px;
  box-sizing: border-box;
}

.tab-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 商品卡头 */
.item-card {
  display: flex;
  gap: 10px;
  padding: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.item-cover-wrap {
  width: 76px;
  height: 76px;
  border-radius: 6px;
  overflow: hidden;
  flex-shrink: 0;
  background: #e2e8f0;
}

.item-cover {
  width: 100%;
  height: 100%;
}

.item-cover-empty {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  font-size: 24px;
}

.item-main-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.item-title {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  text-decoration: none;
  line-height: 1.35;
}

.item-title:hover {
  color: var(--xh-primary, #059669);
}

.item-id-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #94a3b8;
  margin-top: 3px;
}

.item-bottom-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 6px;
}

.jump-link {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--xh-primary, #059669);
  text-decoration: none;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
  padding: 2px 7px;
  background: var(--xh-primary-soft, #ecfdf5);
  border: 1px solid var(--xh-primary-border, #a7f3d0);
  border-radius: 4px;
  transition: all 0.15s ease;
  line-height: 1.2;
}

.jump-link:hover {
  background: var(--xh-primary, #059669);
  color: #fff;
  text-decoration: none;
}

.item-stats-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}

.stat-chip {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #e2e8f0;
  color: #475569;
}

.status-chip.on_sale {
  background: #dcfce7;
  color: #15803d;
  font-weight: 600;
}

.status-chip.sold {
  background: #fee2e2;
  color: #b91c1c;
}

/* 标价与底价安全矩阵 */
.price-matrix-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.matrix-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.matrix-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.floor-cell {
  border-left: 1px dashed #e2e8f0;
  padding-left: 10px;
}

.m-label {
  font-size: 11px;
  color: #64748b;
}

.m-label-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.edit-floor-btn {
  padding: 0;
  height: auto;
  font-size: 11px;
}

.price-text {
  font-size: 17px;
  font-weight: 700;
  color: #0f172a;
}

.floor-val {
  font-size: 17px;
  font-weight: 700;
  color: #dc2626;
}

.floor-unset-tip {
  font-size: 11px;
  color: #94a3b8;
  line-height: 22px;
}

.floor-edit-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 4px;
}

.floor-input {
  width: 100% !important;
}

.floor-edit-actions {
  display: flex;
  gap: 6px;
}

.profit-bar {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid #f1f5f9;
  font-size: 11px;
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.profit-label {
  color: #64748b;
}

.profit-val {
  color: #059669;
  font-weight: 700;
}

.profit-sub {
  color: #94a3b8;
  font-size: 10px;
}

/* 自动发货卡片 */
.binding-card {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  padding: 10px 12px;
}

.bc-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.bc-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #166534;
}

.bc-body {
  font-size: 12px;
}

.bc-pool-name {
  color: #1e293b;
  font-weight: 500;
}

.bc-stock-row {
  margin-top: 4px;
  font-size: 11px;
  color: #64748b;
}

.stock-val {
  font-weight: 700;
  color: #059669;
}

.stock-val.low-stock {
  color: #dc2626;
}

.stock-warn {
  color: #dc2626;
  margin-left: 4px;
}

/* 快捷促单话术 */
.quick-phrases-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
}

.qp-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.qp-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #334155;
}

.phrases-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.phrase-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.phrase-item:hover {
  background: #f0fdf4;
  border-color: #bbf7d0;
  transform: translateY(-1px);
}

.phrase-tag {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}

.phrase-tag.tag-0 {
  background: #e0f2fe;
  color: #0369a1;
}

.phrase-tag.tag-1 {
  background: #fef3c7;
  color: #b45309;
}

.phrase-tag.tag-2 {
  background: #dcfce7;
  color: #15803d;
}

.phrase-tag.tag-3 {
  background: #f3e8ff;
  color: #7e22ce;
}

.phrase-text {
  font-size: 12px;
  color: #334155;
  line-height: 1.4;
  flex: 1;
}

/* 订单卡片列表 */
.orders-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.order-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.oc-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.oc-amount {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}

.oc-title {
  font-size: 12px;
  font-weight: 500;
  color: #334155;
  line-height: 1.4;
}

.oc-meta-row,
.oc-time-row {
  display: flex;
  align-items: center;
  font-size: 11px;
  color: #64748b;
  gap: 6px;
}

.oc-delivery-preview {
  background: #f8fafc;
  border-radius: 4px;
  padding: 6px 8px;
  font-size: 11px;
  margin-top: 4px;
}

.dp-label {
  color: #94a3b8;
  margin-bottom: 2px;
}

.dp-content {
  color: #0f172a;
  word-break: break-all;
}

.oc-actions {
  margin-top: 4px;
  display: flex;
  justify-content: flex-end;
}

/* 空状态 */
.no-item-box,
.no-order-box {
  padding: 28px 16px;
  text-align: center;
  color: #94a3b8;
}

.no-item-icon,
.no-order-icon {
  font-size: 36px;
  margin-bottom: 8px;
  color: #cbd5e1;
}

.no-item-title,
.no-order-title {
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  margin-bottom: 4px;
}

.no-item-sub,
.no-order-sub {
  font-size: 11px;
  color: #94a3b8;
  line-height: 1.5;
}

/* 风险画像页 */
.risk-tab {
  padding-bottom: 20px;
}
</style>
