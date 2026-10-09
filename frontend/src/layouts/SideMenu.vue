<script setup lang="ts">
import { computed } from 'vue'
import {
  Aim,
  Bell,
  ChatDotRound,
  DataBoard,
  Document,
  Goods,
  Lightning,
  List,
  MagicStick,
  Message,
  Operation,
  Setting,
  Tickets,
  Upload,
  User,
} from '@element-plus/icons-vue'

const props = defineProps<{ active: string; collapsed: boolean }>()

const activeMenu = computed(() => {
  if (props.active.startsWith('/radar')) return '/radar/search'
  return props.active
})
</script>

<template>
  <el-menu
    class="side-menu"
    :default-active="activeMenu"
    :collapse="collapsed"
    :default-openeds="['messages', 'goods', 'orders']"
    router
  >
    <!-- 核心业务区 -->
    <el-menu-item index="/dashboard">
      <el-icon class="menu-icon-primary"><DataBoard /></el-icon>
      <template #title><span>总览</span></template>
    </el-menu-item>

    <!-- 选品雷达（统一工作台入口） -->
    <el-menu-item index="/radar/search">
      <el-icon class="menu-icon-primary"><Aim /></el-icon>
      <template #title><span>选品雷达</span></template>
    </el-menu-item>

    <!-- 消息中心 -->
    <el-sub-menu index="messages">
      <template #title>
        <el-icon class="menu-icon-primary"><ChatDotRound /></el-icon>
        <span>消息中心</span>
      </template>
      <el-menu-item index="/messages/inbox">
        <el-icon class="sub-icon"><Message /></el-icon>
        <template #title><span>收件箱</span></template>
      </el-menu-item>
      <el-menu-item index="/messages/rules">
        <el-icon class="sub-icon"><Operation /></el-icon>
        <template #title><span>回复规则</span></template>
      </el-menu-item>
    </el-sub-menu>

    <!-- 商品中心 -->
    <el-sub-menu index="goods">
      <template #title>
        <el-icon class="menu-icon-primary"><Goods /></el-icon>
        <span>商品中心</span>
      </template>
      <el-menu-item index="/goods/items">
        <el-icon class="sub-icon"><List /></el-icon>
        <template #title><span>商品管理</span></template>
      </el-menu-item>
      <el-menu-item index="/goods/publish">
        <el-icon class="sub-icon"><Upload /></el-icon>
        <template #title><span>发布商品</span></template>
      </el-menu-item>
    </el-sub-menu>

    <!-- 订单发货 -->
    <el-sub-menu index="orders">
      <template #title>
        <el-icon class="menu-icon-primary"><Tickets /></el-icon>
        <span>订单发货</span>
      </template>
      <el-menu-item index="/orders/list">
        <el-icon class="sub-icon"><Document /></el-icon>
        <template #title><span>订单管理</span></template>
      </el-menu-item>
      <el-menu-item index="/orders/cards">
        <el-icon class="sub-icon"><Lightning /></el-icon>
        <template #title><span>自动发货</span></template>
      </el-menu-item>
    </el-sub-menu>

    <!-- 分隔线与配置/系统管理区域 -->
    <div class="menu-divider" />
    <div v-if="!collapsed" class="menu-group-title">配置与系统</div>

    <el-menu-item index="/accounts">
      <el-icon class="menu-icon-primary"><User /></el-icon>
      <template #title><span>账号配置</span></template>
    </el-menu-item>

    <el-menu-item index="/llm">
      <el-icon class="menu-icon-primary"><MagicStick /></el-icon>
      <template #title><span>模型配置</span></template>
    </el-menu-item>

    <el-menu-item index="/notify">
      <el-icon class="menu-icon-primary"><Bell /></el-icon>
      <template #title><span>通知设置</span></template>
    </el-menu-item>

    <el-menu-item index="/system">
      <el-icon class="menu-icon-primary"><Setting /></el-icon>
      <template #title><span>系统设置</span></template>
    </el-menu-item>
  </el-menu>
</template>

<style scoped>
.side-menu {
  border-right: none;
  padding: 8px 0 28px;
  user-select: none;
}
.side-menu:not(.el-menu--collapse) {
  width: 216px;
}

/* 一级菜单项与父级标题 */
:deep(.el-menu-item),
:deep(.el-sub-menu__title) {
  height: 40px;
  line-height: 40px;
  margin: 3px 10px;
  padding: 0 12px !important;
  border-radius: 8px;
  color: #374151;
  font-size: 13.5px;
  font-weight: 500;
  transition: all 0.18s ease;
}

:deep(.el-menu-item:hover),
:deep(.el-sub-menu__title:hover) {
  background-color: #f3f4f6;
  color: #111827;
}

/* 一级主图标 */
:deep(.menu-icon-primary) {
  font-size: 17px;
  margin-right: 10px;
  color: #6b7280;
  transition: color 0.18s ease;
}

:deep(.el-menu-item:hover .menu-icon-primary),
:deep(.el-sub-menu__title:hover .menu-icon-primary) {
  color: var(--xh-primary, #1e9e6a);
}

/* 二级子菜单项样式（紧凑 + 缩进层次） */
:deep(.el-sub-menu .el-menu) {
  background: transparent;
  padding: 2px 0 4px;
}

:deep(.el-sub-menu .el-menu-item) {
  height: 36px;
  line-height: 36px;
  margin: 2px 10px 2px 14px;
  padding-left: 28px !important;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 400;
  color: #4b5563;
  transition: all 0.15s ease;
}

:deep(.el-sub-menu .el-menu-item:hover) {
  background-color: #f3f4f6;
  color: #111827;
}

/* 二级子图标（稍小巧，色彩低调自然） */
:deep(.sub-icon) {
  font-size: 14.5px;
  margin-right: 8px;
  color: #9ca3af;
  transition: all 0.15s ease;
}

:deep(.el-sub-menu .el-menu-item:hover .sub-icon) {
  color: var(--xh-primary, #1e9e6a);
}

/* 激活状态（Active Highlighting） */
:deep(.el-menu-item.is-active) {
  background: rgba(30, 158, 106, 0.1) !important;
  color: var(--xh-primary, #1e9e6a) !important;
  font-weight: 600;
}

:deep(.el-menu-item.is-active .menu-icon-primary),
:deep(.el-menu-item.is-active .sub-icon) {
  color: var(--xh-primary, #1e9e6a) !important;
}

/* 分隔线与分组标签 */
.menu-divider {
  height: 1px;
  background: #f0f2f5;
  margin: 12px 16px 8px;
}

.menu-group-title {
  padding: 6px 18px 4px;
  font-size: 11px;
  font-weight: 600;
  color: #9ca3af;
  letter-spacing: 0.5px;
}

/* 折叠状态调整 */
.el-menu--collapse :deep(.el-menu-item),
.el-menu--collapse :deep(.el-sub-menu__title) {
  margin: 4px 6px;
  padding: 0 !important;
  justify-content: center;
}

.el-menu--collapse .menu-divider {
  margin: 10px 8px;
}
</style>
