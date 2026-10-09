import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { getItem, TOKEN_KEY } from '@/utils/storage'
import { useAuthStore } from '@/stores/auth'
import AppLayout from '@/layouts/AppLayout.vue'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    public?: boolean
    adminOnly?: boolean
  }
}

const routes: RouteRecordRaw[] = [
  { path: '/login', component: () => import('@/views/LoginView.vue'), meta: { title: '登录', public: true } },
  {
    path: '/',
    component: AppLayout,
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: '总览' } },
      { path: 'accounts', component: () => import('@/views/AccountsView.vue'), meta: { title: '账号中心' } },
      { path: 'radar/tasks', component: () => import('@/views/RadarTasksView.vue'), meta: { title: '选品任务' } },
      { path: 'radar/results', component: () => import('@/views/RadarResultsView.vue'), meta: { title: '好货看板' } },
      { path: 'messages/inbox', component: () => import('@/views/InboxView.vue'), meta: { title: '收件箱' } },
      { path: 'messages/rules', component: () => import('@/views/ReplyRulesView.vue'), meta: { title: '回复规则' } },
      { path: 'goods/items', component: () => import('@/views/GoodsItemsView.vue'), meta: { title: '商品管理' } },
      { path: 'goods/publish', component: () => import('@/views/GoodsPublishView.vue'), meta: { title: '发布商品' } },
      { path: 'orders/list', component: () => import('@/views/OrdersView.vue'), meta: { title: '订单' } },
      { path: 'orders/cards', component: () => import('@/views/CardsView.vue'), meta: { title: '卡券' } },
      { path: 'notify', component: () => import('@/views/NotifyView.vue'), meta: { title: '通知设置' } },
      { path: 'llm', component: () => import('@/views/LlmView.vue'), meta: { title: '模型接入' } },
      { path: 'system', component: () => import('@/views/SystemView.vue'), meta: { title: '系统' } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  if (to.meta.public) return true
  if (!getItem(TOKEN_KEY)) return { path: '/login', query: { redirect: to.fullPath } }
  if (to.meta.adminOnly && !useAuthStore().isAdmin) return '/dashboard'
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} - 鱼塘管家` : '鱼塘管家'
})

export default router
