import Taro from '@tarojs/taro'
const KEY = 'levelup.auth.v1'
let token = '', epoch = 0, initialized = false
const listeners = new Set<() => void>()
export function credentials() {
  if (!initialized) {
    initialized = true
    try { token = Taro.getStorageSync(KEY)?.token || '' } catch {}
  }
  return { token, epoch }
}
export function saveCredentials(value: string) {
  Taro.setStorageSync(KEY, { token: value })
  token = value; initialized = true; epoch++
}
export function clearCredentials() {
  try { Taro.removeStorageSync(KEY) } catch {}
  token = ''; initialized = true; epoch++
  listeners.forEach(listener => listener())
}
export function onCredentialsCleared(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}
