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
/** 本机免登录签发的会话（界面隐藏退出登录 / 修改密码） */
export const LOCAL_KEY = 'xh_local'
