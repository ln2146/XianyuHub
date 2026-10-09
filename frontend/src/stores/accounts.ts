import { defineStore } from 'pinia'
import { ref } from 'vue'
import { listAccounts, type Account } from '@/api/account'

/** 账号列表缓存：多个页面需要账号下拉框 */
export const useAccountsStore = defineStore('accounts', () => {
  const list = ref<Account[]>([])
  const loaded = ref(false)

  async function load(force = false) {
    if (loaded.value && !force) return list.value
    list.value = await listAccounts()
    loaded.value = true
    return list.value
  }

  function nameOf(id: number | null | undefined): string {
    if (id === null || id === undefined) return '-'
    const a = list.value.find((x) => x.id === id)
    if (!a) return `#${id}`
    return a.remark || a.nickname || a.unb
  }

  return { list, loaded, load, nameOf }
})
