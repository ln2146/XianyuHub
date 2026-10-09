<script setup lang="ts">
// 行情展示：建议价 + 更便宜的竞品
import type { MarketView } from '@/api/goods'
import { fmtMoney } from '@/utils/format'

defineProps<{ data: MarketView; myPrice?: number | null }>()
const emit = defineEmits<{ (e: 'pick', price: number): void }>()
</script>

<template>
  <div class="market">
    <div class="muted small">关键词「{{ data.keyword }}」· 有效样本 {{ data.sample }} 个</div>
    <el-empty v-if="!data.suggestion" description="样本不足，无法给出建议价" :image-size="50" />
    <template v-else>
      <div class="sugs">
        <div class="sug" @click="emit('pick', data.suggestion.quick_sale)">
          <div class="label">快速出手</div>
          <div class="val">{{ fmtMoney(data.suggestion.quick_sale) }}</div>
        </div>
        <div class="sug main" @click="emit('pick', data.suggestion.market)">
          <div class="label">市场价</div>
          <div class="val">{{ fmtMoney(data.suggestion.market) }}</div>
        </div>
        <div class="sug" @click="emit('pick', data.suggestion.premium)">
          <div class="label">溢价</div>
          <div class="val">{{ fmtMoney(data.suggestion.premium) }}</div>
        </div>
      </div>
      <div class="muted small basis">
        区间 {{ fmtMoney(data.suggestion.basis.min) }} ~ {{ fmtMoney(data.suggestion.basis.max) }}，
        P25 {{ fmtMoney(data.suggestion.basis.p25) }}，中位数 {{ fmtMoney(data.suggestion.basis.median) }}，P75 {{ fmtMoney(data.suggestion.basis.p75) }}
        <template v-if="myPrice"> · 你的价格 {{ fmtMoney(myPrice) }}</template>
      </div>
    </template>
    <template v-if="data.cheaper_competitors.length">
      <div class="sub-title">比你便宜的在售商品</div>
      <div v-for="(c, i) in data.cheaper_competitors" :key="i" class="comp">
        <el-link :href="c.link" target="_blank" class="ellipsis comp-title">{{ c.title }}</el-link>
        <span class="muted small">{{ c.area }}</span>
        <span class="comp-price">{{ fmtMoney(c.price) }}</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.sugs {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin: 10px 0 6px;
}
.sug {
  border: 1px solid var(--xh-border);
  border-radius: 8px;
  padding: 10px;
  text-align: center;
  cursor: pointer;
}
.sug:hover {
  border-color: var(--xh-primary);
}
.sug.main {
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-5);
}
.label {
  font-size: 12px;
  color: var(--xh-muted);
}
.val {
  font-size: 18px;
  font-weight: 700;
  margin-top: 4px;
}
.basis {
  line-height: 1.6;
}
.sub-title {
  font-weight: 600;
  margin: 12px 0 6px;
}
.comp {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--xh-border);
}
.comp-title {
  flex: 1;
  min-width: 0;
  justify-content: flex-start;
}
.comp-price {
  color: #f56c6c;
  font-weight: 600;
}
</style>
