<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
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
  SetUp,
  Tickets,
  Upload,
  User,
} from '@element-plus/icons-vue'

import { useAccountsStore } from '@/stores/accounts'
import { useAuthStore } from '@/stores/auth'
import { usePrefsStore } from '@/stores/prefs'
import { useRealtimeStore } from '@/stores/realtime'

const props = defineProps<{ active: string; collapsed: boolean }>()
const prefs = usePrefsStore()
const realtime = useRealtimeStore()
const unreadCount = computed(() => realtime.totalUnread)

// 有账号掉登录 / 被限制 / 消息断线时在「账号配置」上标红点：否则卖家要等发现没自动回复才知道
const accounts = useAccountsStore()
const auth = useAuthStore()
const accountAlerts = computed(() => accounts.attention.length)
let healthTimer: number | undefined
onMounted(() => {
  accounts.refreshHealth()
  healthTimer = window.setInterval(() => accounts.refreshHealth(), 60_000)
})
onBeforeUnmount(() => window.clearInterval(healthTimer))

const activeMenu = computed(() => {
  if (props.active.startsWith('/radar')) return '/radar/smart'
  return props.active
})
</script>

<template>
  <el-menu
    class="side-menu"
    :default-active="activeMenu"
    :collapse="collapsed"
    :default-openeds="['goods', 'orders']"
    router
  >
    <!-- 核心业务区 -->
    <el-menu-item index="/dashboard">
      <el-icon class="menu-icon-primary"><DataBoard /></el-icon>
      <template #title><span>总览</span></template>
    </el-menu-item>

    <!-- 选品雷达（统一工作台入口） -->
    <el-menu-item v-if="prefs.showBuyer" index="/radar/smart">
      <el-icon class="menu-icon-primary"><Aim /></el-icon>
      <template #title><span>选品雷达</span></template>
    </el-menu-item>

    <!-- 商品中心 -->
    <el-sub-menu v-if="prefs.showSeller" index="goods">
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
    <el-sub-menu v-if="prefs.showSeller" index="orders">
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

    <!-- 消息中心 -->
    <el-sub-menu v-if="prefs.showSeller" index="messages">
      <template #title>
        <el-icon class="menu-icon-primary"><ChatDotRound /></el-icon>
        <span class="sub-menu-title-row">
          <span>消息中心</span>
          <span v-if="unreadCount > 0" class="menu-dot-badge" />
        </span>
      </template>
      <el-menu-item index="/messages/inbox">
        <el-icon class="sub-icon"><Message /></el-icon>
        <template #title>
          <div class="menu-item-row">
            <span>在线消息</span>
            <el-badge v-if="unreadCount > 0" :value="unreadCount" :max="99" class="unread-badge" />
          </div>
        </template>
      </el-menu-item>
      <el-menu-item index="/messages/rules">
        <el-icon class="sub-icon"><Operation /></el-icon>
        <template #title><span>自动回复</span></template>
      </el-menu-item>
    </el-sub-menu>

    <!-- 系统配置 -->
    <el-sub-menu index="settings">
      <template #title>
        <el-icon class="menu-icon-primary"><Setting /></el-icon>
        <span class="sub-menu-title-row">
          <span>系统配置</span>
          <span v-if="accountAlerts > 0" class="menu-dot-badge" />
        </span>
      </template>
      <el-menu-item index="/accounts">
        <el-icon class="sub-icon"><User /></el-icon>
        <template #title>
          <div class="menu-item-row" :title="accountAlerts ? `${accountAlerts} 个账号需要处理` : undefined">
            <span>账号配置</span>
            <el-badge v-if="accountAlerts > 0" :value="accountAlerts" type="danger" class="unread-badge" />
          </div>
        </template>
      </el-menu-item>
      <el-menu-item v-if="auth.isAdmin" index="/llm">
        <el-icon class="sub-icon"><MagicStick /></el-icon>
        <template #title><span>模型配置</span></template>
      </el-menu-item>
      <el-menu-item index="/notify">
        <el-icon class="sub-icon"><Bell /></el-icon>
        <template #title><span>通知设置</span></template>
      </el-menu-item>
      <el-menu-item index="/system">
        <el-icon class="sub-icon"><SetUp /></el-icon>
        <template #title><span>系统设置</span></template>
      </el-menu-item>
    </el-sub-menu>
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
  border-radius: var(--xh-radius-sm);
  color: var(--xh-text);
  font-size: var(--xh-fs-sm);
  font-weight: 500;
  transition: all 0.18s ease;
}

:deep(.el-menu-item:hover),
:deep(.el-sub-menu__title:hover) {
  background-color: var(--xh-fill);
  color: var(--xh-text);
}

/* 一级主图标 */
:deep(.menu-icon-primary) {
  font-size: var(--xh-fs-lg);
  margin-right: 10px;
  color: var(--xh-muted);
  transition: color 0.18s ease;
}

:deep(.el-menu-item:hover .menu-icon-primary),
:deep(.el-sub-menu__title:hover .menu-icon-primary) {
  color: var(--xh-primary);
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
  border-radius: var(--xh-radius-sm);
  font-size: var(--xh-fs-sm);
  font-weight: 400;
  color: var(--xh-text-2);
  transition: all 0.15s ease;
}

:deep(.el-sub-menu .el-menu-item:hover) {
  background-color: var(--xh-fill);
  color: var(--xh-text);
}

/* 二级子图标（稍小巧，色彩低调自然） */
:deep(.sub-icon) {
  font-size: var(--xh-fs-md);
  margin-right: 8px;
  color: var(--xh-muted);
  transition: all 0.15s ease;
}

:deep(.el-sub-menu .el-menu-item:hover .sub-icon) {
  color: var(--xh-primary);
}

/* 激活状态（Active Highlighting） */
:deep(.el-menu-item.is-active) {
  background: var(--xh-primary-soft) !important;
  color: var(--xh-primary) !important;
  font-weight: 600;
}

:deep(.el-menu-item.is-active .menu-icon-primary),
:deep(.el-menu-item.is-active .sub-icon) {
  color: var(--xh-primary) !important;
}

/* 折叠状态调整 */
.el-menu--collapse :deep(.el-menu-item),
.el-menu--collapse :deep(.el-sub-menu__title) {
  margin: 4px 6px;
  padding: 0 !important;
  justify-content: center;
}

.sub-menu-title-row {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.menu-dot-badge {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background-color: var(--el-color-danger);
  flex-shrink: 0;
}
.menu-item-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding-right: 8px;
}
.unread-badge :deep(.el-badge__content) {
  font-size: 11px;
  height: 16px;
  line-height: 16px;
  padding: 0 5px;
}
</style>
