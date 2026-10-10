import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { http } from '@/api/http'
import { listAccounts, type Account } from '@/api/account'
import type { ImStatus } from '@/api/message'

/** 账号列表缓存：多个页面需要账号下拉框；同时汇总哪些账号需要卖家处理 */
export const useAccountsStore = defineStore('accounts', () => {
  const list = ref<Account[]>([])
  const loaded = ref(false)
  const im = ref<ImStatus['accounts']>({})

  async function load(force = false) {
    if (loaded.value && !force) return list.value
    list.value = await listAccounts()
    loaded.value = true
    return list.value
  }

  /** 静默刷新账号状态与消息连接（定时调用，失败不弹提示） */
  async function refreshHealth() {
    try {
      const [accs, st] = await Promise.all([
        http.get<Account[]>('/accounts', { silent: true }).then((r) => r.data),
        http.get<ImStatus>('/messages/im-status', { silent: true }).then((r) => r.data),
      ])
      list.value = accs
      loaded.value = true
      im.value = st.accounts || {}
    } catch {
      /* 静默 */
    }
  }

  function nameOf(id: number | null | undefined): string {
    if (id === null || id === undefined) return '-'
    const a = list.value.find((x) => x.id === id)
    if (!a) return `#${id}`
    return a.remark || a.nickname || a.unb
  }

  /** 账号当前需要卖家处理的问题；正常 / 已停用返回 null */
  function problemOf(a: Account | undefined | null): string | null {
    if (!a) return null
    if (a.status === 'need_login') return '登录已失效，需要重新登录'
    if (a.status === 'circuit_open') return '被闲鱼限制，需要到闲鱼完成验证'
    const st = im.value[String(a.id)]
    if (a.status === 'active' && st && !st.connected) return '消息连接已断开，正在自动重连'
    return null
  }

  const attention = computed(() => list.value.filter((a) => problemOf(a)))

  return { list, loaded, im, load, refreshHealth, nameOf, problemOf, attention }
})
