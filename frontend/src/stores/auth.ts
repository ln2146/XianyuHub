import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as api from '@/api/system'
import type { UserOut } from '@/api/system'
import { getItem, removeItem, setItem, TOKEN_KEY, USER_KEY } from '@/utils/storage'

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

  async function login(username: string, password: string) {
    const res = await api.login(username, password)
    token.value = res.access_token
    user.value = res.user
    setItem(TOKEN_KEY, res.access_token)
    setItem(USER_KEY, JSON.stringify(res.user))
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
  }

  return { token, user, isAdmin, login, refreshMe, logout }
})
