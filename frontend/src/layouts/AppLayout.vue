<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { ArrowDown, Expand, Fold } from '@element-plus/icons-vue'
import SideMenu from './SideMenu.vue'
import { useAuthStore } from '@/stores/auth'
import { usePrefsStore, usageModeLabels, type UsageMode } from '@/stores/prefs'
import { useRealtimeStore } from '@/stores/realtime'
import { useMobile } from '@/composables/useMobile'
import { roleMap } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const prefs = usePrefsStore()
const realtime = useRealtimeStore()
const isMobile = useMobile()

const collapsed = ref(false)
const drawerOpen = ref(false)

const active = computed(() => route.path)

const breadcrumb = computed(() => {
  const p = route.path
  if (p === '/dashboard') return [{ label: '工作台' }, { label: '总览' }]
  if (p.startsWith('/radar')) {
    const sub = p.includes('smart') ? '智能搜索' : p.includes('search') ? '实时搜货' : '价格监控'
    return [{ label: '选品雷达' }, { label: sub }]
  }
  if (p.startsWith('/goods')) {
    const sub = p.includes('publish') ? '发布商品' : '商品管理'
    return [{ label: '商品中心' }, { label: sub }]
  }
  if (p.startsWith('/orders')) {
    const sub = p.includes('cards') ? '自动发货' : '订单管理'
    return [{ label: '订单发货' }, { label: sub }]
  }
  if (p.startsWith('/messages')) {
    const sub = p.includes('inbox') ? '在线客服' : '回复规则'
    return [{ label: '消息中心' }, { label: sub }]
  }
  if (['/accounts', '/llm', '/notify', '/system'].some((x) => p.startsWith(x))) {
    const nameMap: Record<string, string> = {
      '/accounts': '账号配置',
      '/llm': '模型配置',
      '/notify': '通知设置',
      '/system': '系统设置',
    }
    return [{ label: '系统配置' }, { label: nameMap[p] || (route.meta.title as string) || '' }]
  }
  return [{ label: (route.meta.title as string) || '页面' }]
})

watch(
  () => route.path,
  () => {
    drawerOpen.value = false
  },
)

onMounted(() => {
  realtime.connect()
  auth.refreshMe().catch(() => undefined)
})
onBeforeUnmount(() => realtime.disconnect())

async function logout() {
  await ElMessageBox.confirm('确定退出登录？', '提示', { type: 'warning' })
  realtime.disconnect()
  auth.logout()
  router.replace('/login')
}

function onCommand(cmd: string) {
  if (cmd.startsWith('mode:')) prefs.setMode(cmd.slice(5) as UsageMode)
  else if (cmd === 'logout') logout()
  else if (cmd === 'password') router.push({ path: '/system', query: { tab: 'password' } })
}
</script>

<template>
  <el-container class="layout">
    <!-- 桌面端侧边栏 -->
    <el-aside v-if="!isMobile" :width="collapsed ? '64px' : '216px'" class="aside">
      <div class="brand" :class="{ mini: collapsed }">
        <img src="/icon.svg" alt="" />
        <span v-if="!collapsed">鱼塘管家</span>
      </div>
      <el-scrollbar>
        <SideMenu :active="active" :collapsed="collapsed" />
      </el-scrollbar>
    </el-aside>

    <!-- 移动端抽屉菜单 -->
    <el-drawer v-else v-model="drawerOpen" direction="ltr" size="240px" :with-header="false" class="menu-drawer">
      <div class="brand">
        <img src="/icon.svg" alt="" />
        <span>鱼塘管家</span>
      </div>
      <SideMenu :active="active" :collapsed="false" />
    </el-drawer>

    <el-container class="main-col">
      <el-header class="header">
        <div class="header-left">
          <el-button text class="fold-btn" @click="isMobile ? (drawerOpen = true) : (collapsed = !collapsed)">
            <el-icon :size="18"><Expand v-if="isMobile || collapsed" /><Fold v-else /></el-icon>
          </el-button>
          <nav class="header-breadcrumb" aria-label="位置导航">
            <template v-for="(item, idx) in breadcrumb" :key="idx">
              <span v-if="idx > 0" class="crumb-sep">/</span>
              <span class="crumb-text" :class="{ 'is-last': idx === breadcrumb.length - 1 }">{{ item.label }}</span>
            </template>
          </nav>
        </div>
        <div class="header-right">
          <el-tooltip :content="realtime.connected ? '实时推送已连接' : '实时推送未连接，正在重试'">
            <span class="dot" :class="{ on: realtime.connected }" />
          </el-tooltip>
          <el-dropdown trigger="click" @command="onCommand">
            <span class="user">
              <el-avatar :size="28" class="avatar">{{ (auth.user?.username || '?').slice(0, 1).toUpperCase() }}</el-avatar>
              <span v-if="!isMobile" class="uname">{{ auth.user?.username }}</span>
              <el-tag v-if="!isMobile" size="small" effect="plain" round>{{ roleMap[auth.user?.role || ''] || auth.user?.role }}</el-tag>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="(label, m) in usageModeLabels"
                  :key="m"
                  :command="`mode:${m}`"
                  :class="{ 'mode-on': prefs.mode === m }"
                >
                  {{ prefs.mode === m ? '✓ ' : '' }}{{ label }}
                </el-dropdown-item>
                <el-dropdown-item command="password" divided>修改密码</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="main">
        <router-view v-slot="{ Component, route }">
          <keep-alive :include="['RadarSmartView', 'RadarSearchView', 'RadarWatchView']">
            <component :is="Component" :key="route.path" />
          </keep-alive>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>


<style scoped>
.layout {
  height: 100vh;
}
.aside {
  background: #fff;
  border-right: 1px solid var(--xh-border);
  display: flex;
  flex-direction: column;
  transition: width 0.2s;
  overflow: hidden;
}
.brand {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 18px;
  font-weight: 700;
  font-size: 16px;
  color: var(--xh-primary);
  white-space: nowrap;
  flex-shrink: 0;
}
.brand.mini {
  padding: 0 16px;
}
.brand img {
  width: 30px;
  height: 30px;
}
:deep(.side-menu) {
  border-right: none;
}
:deep(.side-menu:not(.el-menu--collapse)) {
  width: 216px;
}
.main-col {
  min-width: 0;
}
.header {
  height: 56px;
  background: #fff;
  border-bottom: 1px solid var(--xh-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px 0 4px;
}
.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.header-breadcrumb {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  user-select: none;
}
.crumb-text {
  color: var(--xh-muted);
  transition: color 0.15s ease;
}
.crumb-text.is-last {
  color: var(--xh-text);
  font-weight: 600;
}
.crumb-sep {
  color: var(--xh-disabled);
  font-size: 11px;
}
.user {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  outline: none;
}
.avatar {
  background: var(--xh-primary);
  color: #fff;
  font-weight: 600;
}
.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #c0c4cc;
  margin-right: 6px;
}
.dot.on {
  background: #67c23a;
  box-shadow: 0 0 0 3px rgba(103, 194, 58, 0.18);
}
.main {
  padding: 20px;
  overflow-y: auto;
}
@media (max-width: 768px) {
  .main {
    padding: 12px;
  }
}
:deep(.menu-drawer .el-drawer__body) {
  padding: 0;
}
</style>
