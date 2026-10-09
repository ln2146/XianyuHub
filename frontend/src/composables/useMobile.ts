import { onBeforeUnmount, onMounted, ref } from 'vue'

/** 是否为窄屏（手机） */
export function useMobile(breakpoint = 768) {
  const isMobile = ref(typeof window !== 'undefined' && window.innerWidth < breakpoint)
  const update = () => {
    isMobile.value = window.innerWidth < breakpoint
  }
  onMounted(() => window.addEventListener('resize', update))
  onBeforeUnmount(() => window.removeEventListener('resize', update))
  return isMobile
}
