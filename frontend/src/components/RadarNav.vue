<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Aim, Search, Timer, TrendCharts } from '@element-plus/icons-vue'

const props = defineProps<{
  current: 'search' | 'results' | 'tasks'
}>()

const router = useRouter()
const route = useRoute()

const tabs = [
  { id: 'search', label: '实时搜货', icon: Search, path: '/radar/search' },
  { id: 'results', label: '好货看板', icon: TrendCharts, path: '/radar/results' },
  { id: 'tasks', label: '监控任务', icon: Timer, path: '/radar/tasks' },
] as const

const subtitle = computed(() => {
  switch (props.current) {
    case 'search':
      return '实时搜索闲鱼商品，即查即看；遇到满意条件可一键开启全自动后台蹲守'
    case 'results':
      return '后台雷达自动巡检、智能评分并拦截风险后的优质货源'
    case 'tasks':
      return '配置自动化巡检关键词与策略，系统定时发现低价货源并推送到好货看板'
  }
})

function switchTab(path: string) {
  if (route.path !== path) {
    router.push(path)
  }
}
</script>

<template>
  <div class="radar-nav-wrap">
    <div class="radar-header">
      <div class="header-left">
        <div class="title-row">
          <span class="hub-icon"><el-icon><Aim /></el-icon></span>
          <h2 class="title">选品雷达</h2>
        </div>
        <div class="sub">{{ subtitle }}</div>
      </div>
      <div class="header-actions">
        <slot name="actions" />
      </div>
    </div>

    <!-- 顶部统一工作台导航选项卡 -->
    <div class="radar-tabs">
      <button
        v-for="t in tabs"
        :key="t.id"
        type="button"
        class="tab-btn"
        :class="{ active: current === t.id }"
        @click="switchTab(t.path)"
      >
        <el-icon class="tab-icon"><component :is="t.icon" /></el-icon>
        <span class="tab-label">{{ t.label }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.radar-nav-wrap {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-bottom: 2px;
}

.radar-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.header-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.hub-icon {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(30, 158, 106, 0.12);
  color: var(--xh-primary, #1e9e6a);
  font-size: 17px;
}

.title {
  margin: 0;
  font-size: 19px;
  font-weight: 700;
  color: var(--xh-text, #1f2329);
  letter-spacing: 0.2px;
}

.sub {
  color: var(--xh-muted, #8a919f);
  font-size: 13px;
  line-height: 1.4;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

/* 工作台选项卡 */
.radar-tabs {
  display: inline-flex;
  align-items: center;
  background: #eef2f0;
  padding: 3px;
  border-radius: 10px;
  gap: 3px;
  align-self: flex-start;
  user-select: none;
}

.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  border-radius: 7px;
  border: none;
  background: transparent;
  color: #4b5563;
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.18s ease;
  line-height: 20px;
}

.tab-btn:hover {
  color: #111827;
  background: rgba(255, 255, 255, 0.6);
}

.tab-btn.active {
  background: #ffffff;
  color: var(--xh-primary, #1e9e6a);
  font-weight: 600;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

.tab-icon {
  font-size: 15px;
}

@media (max-width: 768px) {
  .radar-tabs {
    width: 100%;
    justify-content: space-between;
  }
  .tab-btn {
    flex: 1;
    justify-content: center;
    padding: 6px 8px;
    font-size: 12.5px;
  }
}
</style>
