import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { getItem, MODE_KEY, setItem } from '@/utils/storage'

/** 使用模式：只买东西的人不必看到商品、订单、消息这些卖家功能 */
export type UsageMode = 'all' | 'buyer' | 'seller'

export const usageModeLabels: Record<UsageMode, string> = {
  all: '买卖都用',
  buyer: '主要买东西',
  seller: '主要卖东西',
}

export const usePrefsStore = defineStore('prefs', () => {
  const saved = getItem(MODE_KEY)
  const mode = ref<UsageMode>(saved === 'buyer' || saved === 'seller' ? saved : 'all')
  const showBuyer = computed(() => mode.value !== 'seller')
  const showSeller = computed(() => mode.value !== 'buyer')

  function setMode(m: UsageMode) {
    mode.value = m
    setItem(MODE_KEY, m)
  }

  return { mode, showBuyer, showSeller, setMode }
})
