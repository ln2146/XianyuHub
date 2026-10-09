<script setup lang="ts">
// 选品雷达页头：一行 = 标题 + 分段页签 + 右侧操作（说明文字收进提示图标）
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Aim, Bell, InfoFilled, MagicStick, Search } from '@element-plus/icons-vue'

const props = defineProps<{
  current: 'smart' | 'search' | 'watch'
}>()

const router = useRouter()
const route = useRoute()

const tabs = [
  { id: 'smart', label: '智能搜索', icon: MagicStick, path: '/radar/smart' },
  { id: 'search', label: '实时搜货', icon: Search, path: '/radar/search' },
  { id: 'watch', label: '价格监控', icon: Bell, path: '/radar/watch' },
] as const

const hint = computed(
  () =>
    ({
      smart: '按关键词定时搜索闲鱼，AI 帮你挑出低价好货；看中的商品可加入价格监控',
      search: '实时搜索闲鱼商品，即查即看；满意的搜索条件可一键转为智能搜索',
      watch: '盯住看中的单件商品：记录价格走势，到达目标价时提醒你，商品售出或下架自动停止',
    })[props.current],
)

function switchTab(path: string) {
  if (route.path !== path) router.push(path)
}
</script>

<template>
  <div class="radar-nav">
    <div class="title">
      <el-icon class="title-icon"><Aim /></el-icon>
      <h2>选品雷达</h2>
      <el-tooltip :content="hint" placement="bottom-start">
        <el-icon class="hint"><InfoFilled /></el-icon>
      </el-tooltip>
    </div>

    <nav class="tabs" aria-label="选品雷达">
      <button
        v-for="t in tabs"
        :key="t.id"
        type="button"
        class="tab"
        :class="{ active: current === t.id }"
        :aria-current="current === t.id ? 'page' : undefined"
        @click="switchTab(t.path)"
      >
        <el-icon><component :is="t.icon" /></el-icon>
        <span>{{ t.label }}</span>
      </button>
    </nav>

    <div class="actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.radar-nav {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--xh-space-3) var(--xh-space-4);
}
.title {
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
}
.title h2 {
  margin: 0;
  font-size: var(--xh-fs-xl);
  font-weight: 600;
  color: var(--xh-text);
}
.title-icon {
  font-size: var(--xh-fs-xl);
  color: var(--xh-primary);
}
.hint {
  font-size: var(--xh-fs-md);
  color: var(--xh-disabled);
  cursor: help;
}
.hint:hover {
  color: var(--xh-muted);
}
.tabs {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  border-radius: var(--xh-radius-md);
  background: var(--xh-fill-strong);
}
.tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 var(--xh-space-3);
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--xh-text-2);
  font-size: var(--xh-fs-sm);
  font-weight: 500;
  cursor: pointer;
  transition:
    background 0.15s,
    color 0.15s;
}
.tab:hover {
  color: var(--xh-text);
}
.tab.active {
  background: var(--xh-card);
  color: var(--xh-primary);
  font-weight: 600;
  box-shadow: var(--xh-shadow-1);
}
.tab:focus-visible {
  outline: 2px solid var(--xh-primary);
  outline-offset: 1px;
}
.actions {
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
  margin-left: auto;
}
.actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
@media (max-width: 768px) {
  .tabs {
    order: 3;
    width: 100%;
  }
  .tab {
    flex: 1;
    justify-content: center;
  }
}
</style>
