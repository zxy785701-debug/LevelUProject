import { beforeEach, expect, it, vi } from 'vitest'
const taro = vi.hoisted(() => ({ uploadFile: vi.fn(), request: vi.fn(), getStorageSync: vi.fn(), setStorageSync: vi.fn(), removeStorageSync: vi.fn() }))
vi.mock('@tarojs/taro', () => ({ default: taro }))
import { uploadMaterial } from '../src/features-api'
import { saveCredentials, clearCredentials } from '../src/credentials'
beforeEach(() => { vi.clearAllMocks(); vi.stubGlobal('API_BASE', 'http://test'); saveCredentials('token'); taro.uploadFile.mockResolvedValue({ statusCode: 200, data: JSON.stringify({ code: 0, data: { id: 'job-1', status: 'running' } }) }) })
it('文档上传携带账号、页码及幂等标识', async () => {
  const job = await uploadMaterial({ name: 'a.pdf', path: '/tmp/a.pdf', size: 20 }, '1-6', 'key')
  expect(job.id).toBe('job-1')
  expect(taro.uploadFile.mock.calls[0][0]).toMatchObject({ name: 'file', formData: { pages: '1-6' }, header: { Authorization: 'Bearer token', 'Idempotency-Key': 'key' } })
})
it('上传期间切换账号时拒绝旧结果', async () => {
  taro.uploadFile.mockImplementation(async () => { clearCredentials(); return { statusCode: 200, data: '{"code":0,"data":{}}' } })
  await expect(uploadMaterial({ name: 'a.txt', path: 'file', size: 20 }, undefined, 'key')).rejects.toThrow('账号')
})
it('H5 使用 Bearer 上传，不启用跨域 Cookie', async () => {
  vi.stubEnv('TARO_ENV', 'h5')
  await uploadMaterial({ name: 'a.txt', path: 'blob:file', size: 10 }, undefined, 'key')
  expect(taro.uploadFile.mock.calls[0][0].withCredentials).toBe(false)
  vi.unstubAllEnvs()
})
