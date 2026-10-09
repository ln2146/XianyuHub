<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Aim, Bell, MagicStick, Search } from '@element-plus/icons-vue'

const props = defineProps<{
  current: 'smart' | 'search' | 'watch'
}>()

const router = useRouter()
const route = useRoute()

// 找货（智能搜索 / 实时搜货）+ 盯价（价格监控）
const tabs = [
  { id: 'smart', label: '智能搜索', icon: MagicStick, path: '/radar/smart' },
  { id: 'search', label: '实时搜货', icon: Search, path: '/radar/search' },
  { id: 'watch', label: '价格监控', icon: Bell, path: '/radar/watch' },
] as const

const subtitle = computed(() => {
  switch (props.current) {
    case 'smart':
      return '按关键词定时搜索闲鱼，AI 帮你挑出低价好货；看中的商品可加入价格监控'
    case 'search':
      return '实时搜索闲鱼商品，即查即看；满意的搜索条件可一键转为智能搜索'
    case 'watch':
      return '盯住看中的单件商品：记录价格走势，到达目标价时提醒你，商品售出或下架自动停止'
  }
  return ''
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
