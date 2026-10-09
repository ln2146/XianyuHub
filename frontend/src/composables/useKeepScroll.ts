import { nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'

/**
 * 保持并在切回时恢复容器的滚动条位置（配合 KeepAlive 使用）
 */
export function useKeepScroll(containerSelector = '.main') {
  const savedTop = ref(0)
  let container: HTMLElement | null = null

  const onScroll = () => {
    if (container) {
      savedTop.value = container.scrollTop
    }
  }

  const bind = () => {
    container = document.querySelector(containerSelector)
    if (container) {
      container.addEventListener('scroll', onScroll, { passive: true })
    }
  }

  const unbind = () => {
    if (container) {
      savedTop.value = container.scrollTop
      container.removeEventListener('scroll', onScroll)
      container = null
    }
  }

  const restore = () => {
    nextTick(() => {
      requestAnimationFrame(() => {
        const el = document.querySelector(containerSelector)
        if (el && savedTop.value > 0) {
          el.scrollTop = savedTop.value
        }
      })
    })
  }

  onMounted(() => {
    bind()
  })

  onActivated(() => {
    bind()
    restore()
  })

  onDeactivated(() => {
    unbind()
  })

  onBeforeUnmount(() => {
    unbind()
  })
}
