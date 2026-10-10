// localStorage 在隐私模式 / 禁用站点数据时可能抛异常，统一包一层
export function getItem(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

export function setItem(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    /* ignore */
  }
}

export function removeItem(key: string): void {
  try {
    window.localStorage.removeItem(key)
  } catch {
    /* ignore */
  }
}

export const TOKEN_KEY = 'xh_token'
export const USER_KEY = 'xh_user'
/** 使用模式：all / buyer / seller（只影响菜单与上手清单） */
export const MODE_KEY = 'xh_usage_mode'
