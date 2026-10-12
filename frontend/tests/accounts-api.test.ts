import { beforeEach, expect, test, vi } from 'vitest'
const mock = vi.hoisted(() => ({ storage: new Map<string, unknown>(), request: vi.fn() }))
vi.mock('@tarojs/taro', () => ({ default: {
  getStorageSync: (key: string) => mock.storage.get(key),
  setStorageSync: (key: string, value: unknown) => mock.storage.set(key, value),
  removeStorageSync: (key: string) => mock.storage.delete(key),
  request: mock.request,
} }))
import { credentials, saveCredentials, clearCredentials } from '../src/credentials'
import { api, ApiError } from '../src/api'
beforeEach(() => { vi.stubGlobal('API_BASE', 'http://test'); mock.storage.clear(); clearCredentials(); mock.request.mockReset() })
test('requests carry the business token', async () => {
  saveCredentials('first')
  mock.request.mockResolvedValue({ statusCode: 200, data: { code: 0, data: { nickname: '甲' } } })
  expect(await api('/api/v1/me')).toEqual({ nickname: '甲' })
  expect(mock.request.mock.calls[0][0].header.Authorization).toBe('Bearer first')
})
test('401 clears the session and requires login', async () => {
  saveCredentials('expired')
  mock.request.mockResolvedValue({ statusCode: 401, data: { code: 'AUTH_REQUIRED', message: '请登录' } })
  await expect(api('/api/v1/me')).rejects.toMatchObject({ code: 'AUTH_REQUIRED' })
  expect(credentials().token).toBe('')
})
test('a late response cannot enter another account', async () => {
  saveCredentials('alice')
  let resolve!: (v: unknown) => void
  mock.request.mockReturnValue(new Promise(r => { resolve = r }))
  const pending = api('/api/v1/learning')
  saveCredentials('bob')
  resolve({ statusCode: 200, data: { code: 0, data: { private: 'alice' } } })
  await expect(pending).rejects.toMatchObject({ code: 'SESSION_CHANGED' })
  expect(credentials().token).toBe('bob')
})
test('late 401 does not revoke the new account', async () => {
  saveCredentials('alice')
  let resolve!: (v: unknown) => void
  mock.request.mockReturnValue(new Promise(r => { resolve = r }))
  const pending = api('/api/v1/me')
  saveCredentials('bob')
  resolve({ statusCode: 401, data: { code: 'AUTH_REQUIRED' } })
  await expect(pending).rejects.toBeInstanceOf(ApiError)
  expect(credentials().token).toBe('bob')
})
