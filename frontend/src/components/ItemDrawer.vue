<script setup lang="ts">
// 统一的商品详情抽屉：图片、价格、卖家、描述、AI 判定（插槽）、商品 / 商家分析、操作（插槽）
import { computed, ref, watch } from 'vue'
import { TopRight } from '@element-plus/icons-vue'
import { getItemDetail, type ItemDetail } from '@/api/buyer'
import ItemAnalysisPanel from '@/components/ItemAnalysisPanel.vue'
import { fmtMoney, itemUrl } from '@/utils/format'

export interface DrawerItem {
  title: string
  image: string
  images?: string[]
  price: number | null
  origPrice?: number | null
  wantCnt?: number | null
  browseCnt?: number | null
  area?: string
  sellerNick?: string
  desc?: string
  link?: string
}

const props = defineProps<{
  modelValue: boolean
  itemId: string
  base: DrawerItem | null
  /** 打开时拉取一次商品详情（实时搜货用；智能搜索已存有详情时不必） */
  fetchDetail?: boolean
  accountId?: number | null
  taskId?: number | null
  keyword?: string | null
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const open = computed({ get: () => props.modelValue, set: (v) => emit('update:modelValue', v) })
const detail = ref<ItemDetail | null>(null)
const loading = ref(false)
const descOpen = ref(false)

watch(
  () => [props.modelValue, props.itemId] as const,
  async ([isOpen, id]) => {
    if (!isOpen || !id) return
    detail.value = null
    descOpen.value = false
    if (!props.fetchDetail) return
    loading.value = true
    try {
      detail.value = await getItemDetail(id, props.accountId || null)
    } catch {
      /* 失败时用列表里的基础信息展示 */
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)

const view = computed(() => {
  const b = props.base
  const d = detail.value?.item
  return {
    title: d?.title || b?.title || '',
    images: d?.images?.length ? d.images : b?.images?.length ? b.images : [d?.image_url || b?.image || ''].filter(Boolean),
    price: d?.price ?? b?.price ?? null,
    origPrice: d?.orig_price ?? b?.origPrice ?? null,
    wantCnt: d?.want_cnt ?? b?.wantCnt ?? null,
    browseCnt: d?.browse_cnt ?? b?.browseCnt ?? null,
    area: d?.area || b?.area || '',
    desc: d?.desc || b?.desc || '',
    link: d?.link || b?.link || itemUrl(props.itemId),
  }
})
const seller = computed(() => detail.value?.seller || null)
</script>

<template>
  <el-drawer v-model="open" size="600px" destroy-on-close class="item-drawer">
    <template #header>
      <span class="drawer-title ellipsis">商品详情</span>
    </template>

    <div v-loading="loading" class="body">
      <el-carousel v-if="view.images.length > 1" height="300px" trigger="click" indicator-position="outside">
        <el-carousel-item v-for="(img, i) in view.images" :key="i">
          <el-image :src="img" fit="contain" class="img" referrerpolicy="no-referrer" />
        </el-carousel-item>
      </el-carousel>
      <el-image v-else-if="view.images.length" :src="view.images[0]" fit="contain" class="img single" referrerpolicy="no-referrer" />

      <section class="summary">
        <div class="price-row">
          <span class="price">{{ fmtMoney(view.price) }}</span>
          <span v-if="view.origPrice" class="orig">{{ fmtMoney(view.origPrice) }}</span>
        </div>
        <h3 class="title">{{ view.title }}</h3>
        <div class="stats">
          <span v-if="view.wantCnt">{{ view.wantCnt }} 人想要</span>
          <span v-if="view.browseCnt">{{ view.browseCnt }} 次浏览</span>
          <span v-if="view.area">{{ view.area }}</span>
        </div>
        <div v-if="seller" class="seller">
          <b>{{ seller.nick || base?.sellerNick || '闲鱼卖家' }}</b>
          <el-tag v-if="seller.zhima_level" size="small" type="success">芝麻{{ seller.zhima_level }}</el-tag>
          <el-tag v-if="seller.sold_cnt !== null" size="small" type="info">已售 {{ seller.sold_cnt }} 件</el-tag>
          <el-tag v-if="seller.reg_days" size="small" type="info">来闲鱼 {{ Math.max(1, Math.round(seller.reg_days / 365)) }} 年</el-tag>
          <el-tag v-if="seller.ip_location" size="small" type="info">IP {{ seller.ip_location }}</el-tag>
        </div>
      </section>

      <section v-if="view.desc" class="desc" :class="{ open: descOpen }">
        <div class="desc-text">{{ view.desc }}</div>
        <el-button v-if="view.desc.length > 120" link type="primary" size="small" @click="descOpen = !descOpen">
          {{ descOpen ? '收起' : '展开全文' }}
        </el-button>
      </section>

      <slot name="verdict" />

      <section class="analysis">
        <ItemAnalysisPanel
          :key="itemId"
          :item-id="itemId"
          :task-id="taskId"
          :keyword="keyword"
          :account-id="accountId"
          :ip-location="seller?.ip_location || ''"
          :sold-cnt="seller?.sold_cnt ?? null"
        />
      </section>
    </div>

    <template #footer>
      <div class="footer">
        <slot name="actions" />
        <a :href="view.link" target="_blank" rel="noopener" class="go">
          <el-button type="primary">去闲鱼查看<el-icon class="el-icon--right"><TopRight /></el-icon></el-button>
        </a>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.drawer-title {
  font-size: var(--xh-fs-lg);
  font-weight: 600;
  color: var(--xh-text);
}
.body {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-4);
  min-height: 200px;
}
.img {
  width: 100%;
  height: 300px;
  background: var(--xh-fill);
  border-radius: var(--xh-radius-md);
}
.summary {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.price-row {
  display: flex;
  align-items: baseline;
  gap: var(--xh-space-2);
}
.price {
  font-size: var(--xh-fs-xxl);
  font-weight: 700;
  color: var(--xh-price);
}
.orig {
  font-size: var(--xh-fs-sm);
  color: var(--xh-muted);
  text-decoration: line-through;
}
.title {
  margin: 0;
  font-size: var(--xh-fs-lg);
  font-weight: 600;
  line-height: 1.5;
  color: var(--xh-text);
}
.stats {
  display: flex;
  flex-wrap: wrap;
  gap: var(--xh-space-3);
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}
.seller {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: var(--xh-space-1);
  font-size: var(--xh-fs-sm);
}
.desc {
  padding: var(--xh-space-3);
  border-radius: var(--xh-radius-md);
  background: var(--xh-fill);
}
.desc-text {
  font-size: var(--xh-fs-sm);
  line-height: 1.7;
  color: var(--xh-text-2);
  white-space: pre-wrap;
  display: -webkit-box;
  -webkit-line-clamp: 5;
  line-clamp: 5;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.desc.open .desc-text {
  display: block;
}
.analysis {
  border-top: 1px solid var(--xh-border);
  padding-top: var(--xh-space-3);
}
.footer {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--xh-space-2);
}
.footer :deep(.el-button + .el-button) {
  margin-left: 0;
}
.go {
  text-decoration: none;
}
</style>
