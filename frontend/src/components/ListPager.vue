<script setup lang="ts">
import { nextTick } from 'vue'
import { useMobile } from '@/composables/useMobile'

/** 列表数字分页：桌面端显示总数 / 页码 / 每页条数，手机端精简为小号页码 */
withDefaults(defineProps<{ total: number; pageSizes?: number[]; disabled?: boolean }>(), {
  pageSizes: () => [20, 50, 100, 200],
  disabled: false,
})
const page = defineModel<number>('page', { required: true })
const pageSize = defineModel<number>('pageSize', { required: true })
const emit = defineEmits<{ change: [] }>()
const isMobile = useMobile()

// 改变每页条数时 el-pagination 可能同时触发 current-change，合并为一次 change
let pending = false
function fire() {
  if (pending) return
  pending = true
  nextTick(() => {
    pending = false
    emit('change')
  })
}

function onSize() {
  // 改变每页条数后回到第一页
  page.value = 1
  fire()
}
</script>

<template>
  <div class="list-pager">
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      :page-sizes="pageSizes"
      :layout="isMobile ? 'prev, pager, next' : 'total, prev, pager, next, sizes'"
      :size="isMobile ? 'small' : 'default'"
      :pager-count="isMobile ? 5 : 7"
      :disabled="disabled"
      background
      @current-change="fire"
      @size-change="onSize"
    />
  </div>
</template>

<style scoped>
.list-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
  overflow-x: auto;
}
@media (max-width: 768px) {
  .list-pager {
    justify-content: center;
  }
}
</style>
