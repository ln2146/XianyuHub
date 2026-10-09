<script setup lang="ts">
import {
  Aim,
  Bell,
  ChatDotRound,
  DataBoard,
  Goods,
  MagicStick,
  Search,
  Setting,
  Tickets,
  User,
} from '@element-plus/icons-vue'

defineProps<{ active: string; collapsed: boolean }>()
</script>

<template>
  <el-menu
    class="side-menu"
    :default-active="active"
    :collapse="collapsed"
    :default-openeds="['radar', 'messages', 'goods', 'orders']"
    router
  >
    <!-- 核心业务区 -->
    <el-menu-item index="/dashboard">
      <el-icon><DataBoard /></el-icon>
      <template #title>总览</template>
    </el-menu-item>

    <el-sub-menu index="radar">
      <template #title>
        <el-icon><Aim /></el-icon>
        <span>选品雷达</span>
      </template>
      <el-menu-item index="/radar/search">
        <el-icon><Search /></el-icon>
        <template #title>商品搜索</template>
      </el-menu-item>
      <el-menu-item index="/radar/results">好货看板</el-menu-item>
      <el-menu-item index="/radar/tasks">监控任务</el-menu-item>
    </el-sub-menu>

    <el-sub-menu index="messages">
      <template #title>
        <el-icon><ChatDotRound /></el-icon>
        <span>消息中心</span>
      </template>
      <el-menu-item index="/messages/inbox">收件箱</el-menu-item>
      <el-menu-item index="/messages/rules">回复规则</el-menu-item>
    </el-sub-menu>

    <el-sub-menu index="goods">
      <template #title>
        <el-icon><Goods /></el-icon>
        <span>商品中心</span>
      </template>
      <el-menu-item index="/goods/items">商品</el-menu-item>
      <el-menu-item index="/goods/publish">发布</el-menu-item>
    </el-sub-menu>

    <el-sub-menu index="orders">
      <template #title>
        <el-icon><Tickets /></el-icon>
        <span>订单发货</span>
      </template>
      <el-menu-item index="/orders/list">订单</el-menu-item>
      <el-menu-item index="/orders/cards">自动发货</el-menu-item>
    </el-sub-menu>

    <!-- 分隔线与配置/系统管理区域 -->
    <div class="menu-divider" />
    <div v-if="!collapsed" class="menu-group-title">配置与系统</div>

    <el-menu-item index="/accounts">
      <el-icon><User /></el-icon>
      <template #title>账号配置</template>
    </el-menu-item>

    <el-menu-item index="/llm">
      <el-icon><MagicStick /></el-icon>
      <template #title>模型配置</template>
    </el-menu-item>

    <el-menu-item index="/notify">
      <el-icon><Bell /></el-icon>
      <template #title>通知设置</template>
    </el-menu-item>

    <el-menu-item index="/system">
      <el-icon><Setting /></el-icon>
      <template #title>系统设置</template>
    </el-menu-item>
  </el-menu>
</template>

<style scoped>
.side-menu {
  border-right: none;
  padding-bottom: 24px;
}
.side-menu:not(.el-menu--collapse) {
  width: 216px;
}
.menu-divider {
  height: 1px;
  background: var(--xh-border, #f0f0f0);
  margin: 12px 16px 8px;
}
.menu-group-title {
  padding: 4px 20px 6px;
  font-size: 11px;
  font-weight: 600;
  color: #909399;
  letter-spacing: 0.5px;
}
</style>
