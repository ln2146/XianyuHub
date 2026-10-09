import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as api from '@/api/system'
import type { UserOut } from '@/api/system'
import { getItem, LOCAL_KEY, removeItem, setItem, TOKEN_KEY, USER_KEY } from '@/utils/storage'

function loadUser(): UserOut | null {
  const raw = getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as UserOut
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(getItem(TOKEN_KEY))
  const user = ref<UserOut | null>(loadUser())
  const isAdmin = computed(() => user.value?.role === 'admin')
  const localMode = ref(getItem(LOCAL_KEY) === '1')

  async function login(username: string, password: string) {
    const res = await api.login(username, password)
    token.value = res.access_token
    user.value = res.user
    setItem(TOKEN_KEY, res.access_token)
    setItem(USER_KEY, JSON.stringify(res.user))
    localMode.value = false
    removeItem(LOCAL_KEY)
  }

  /** 本机直接访问时自动登录；不可用（局域网 / 公网 / 已关闭）返回 false */
  async function tryLocalLogin(): Promise<boolean> {
    try {
      const res = await api.localLogin()
      token.value = res.access_token
      user.value = res.user
      localMode.value = true
      setItem(TOKEN_KEY, res.access_token)
      setItem(USER_KEY, JSON.stringify(res.user))
      setItem(LOCAL_KEY, '1')
      return true
    } catch {
      return false
    }
  }

  async function refreshMe() {
    if (!token.value) return
    user.value = await api.me()
    setItem(USER_KEY, JSON.stringify(user.value))
  }

  function logout() {
    token.value = null
    user.value = null
    removeItem(TOKEN_KEY)
    removeItem(USER_KEY)
    localMode.value = false
    removeItem(LOCAL_KEY)
  }

  return { token, user, isAdmin, localMode, login, tryLocalLogin, refreshMe, logout }
})
