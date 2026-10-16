import Taro from '@tarojs/taro'
import { Report, Session, Data } from './domain'
import { credentials, clearCredentials } from './credentials'
export interface User {
  id: string
  nickname: string
  avatar_version: number
  stats: { xp: number; coins: number; level: number; topics: number; streak: number; accuracy: number }
  quota: { remaining: number; daily_limit: number }
}
export class ApiError extends Error {
  constructor(message: string, public code = 'NETWORK_ERROR') { super(message) }
}
export class RequestScope {
  readonly epoch = credentials().epoch
  private closed = false
  private tasks = new Set<ReturnType<typeof Taro.request>>()
  private waits = new Set<() => void>()
  assertCurrent() {
    if (this.epoch !== credentials().epoch) throw new ApiError('账号已切换，请重新操作', 'SESSION_CHANGED')
    if (this.closed) throw new ApiError('已停止本页查询，后台任务仍可恢复', 'REQUEST_CANCELLED')
  }
  track(task: ReturnType<typeof Taro.request>) { this.assertCurrent(); this.tasks.add(task) }
  release(task: ReturnType<typeof Taro.request>) { this.tasks.delete(task) }
  cancel() { this.closed = true; this.tasks.forEach(task => { if (typeof task.abort === 'function') task.abort() }); this.tasks.clear(); this.waits.forEach(stop => stop()); this.waits.clear() }
  sleep(ms: number) {
    this.assertCurrent()
    return new Promise<void>((resolve, reject) => {
      const stop = () => { clearTimeout(timer); this.waits.delete(stop); reject(new ApiError('已停止本页查询', 'REQUEST_CANCELLED')) }
      const timer = setTimeout(() => { this.waits.delete(stop); try { this.assertCurrent(); resolve() } catch (e) { reject(e) } }, ms)
      this.waits.add(stop)
    })
  }
}
let legacyGenerationScope: RequestScope | undefined
export function unwrap<T>(response: { statusCode: number; data: unknown }, session: ReturnType<typeof credentials>): T {
  if (session.epoch !== credentials().epoch) throw new ApiError('账号已切换，请重新操作', 'SESSION_CHANGED')
  const body = response.data as { code: number | string; message: string; data: T }
  if (response.statusCode === 401) clearCredentials()
  if (response.statusCode !== 200 || body.code !== 0) throw new ApiError(body.message || '服务暂时无法完成请求', String(body.code || 'HTTP_ERROR'))
  return body.data
}
export async function api<T>(path: string, method: 'GET' | 'POST' | 'PUT' | 'DELETE' = 'GET', data?: unknown, operationKey?: string, control?: { scope?: RequestScope; timeout?: number }): Promise<T> {
  const session = credentials()
  let task: ReturnType<typeof Taro.request> | undefined
  try {
    control?.scope?.assertCurrent()
    task = Taro.request({ url: API_BASE + path, method, data, timeout: control?.timeout || 100000,
      header: { 'content-type': 'application/json', ...(session.token ? { Authorization: `Bearer ${session.token}` } : {}), ...(operationKey ? { 'Idempotency-Key': operationKey } : {}) },
    })
    control?.scope?.track(task)
    const result = await task
    control?.scope?.assertCurrent()
    return unwrap<T>(result, session)
  } catch (e) {
    if (e instanceof ApiError) throw e
    control?.scope?.assertCurrent()
    throw new ApiError('连接暂时中断，请检查网络后重试。已经提交的学习记录仍保存在云端。')
  } finally { if (task) control?.scope?.release(task) }
}
export const operationKey = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`
export const cancelRequest = (scope = legacyGenerationScope) => scope?.cancel()
export const generateQuiz = (text: string, question_count: 3 | 5, difficulty: 'easy' | 'medium', key: string) => { legacyGenerationScope = new RequestScope(); return api<Session>('/api/v1/quiz/generate', 'POST', { text, question_count, difficulty }, key, { scope: legacyGenerationScope }) }
export const generateReport = (s: Session, key: string) => api<Report>('/api/v1/report/generate', 'POST', { attempt_id: s.id }, key)
export const getLearning = () => api<Data>('/api/v1/learning')
export const submitAnswer = (id: string, question_id: string, selected: string[], elapsed_ms: number) => api<{ session: Session; user: User }>(`/api/v1/attempts/${id}/answers`, 'POST', { question_id, selected, elapsed_ms })
export const saveProgress = (id: string, cursor: number) => api<Session>(`/api/v1/attempts/${id}/progress`, 'PUT', { cursor })
export const replayQuiz = (quiz_id: string) => api<Session>('/api/v1/attempts', 'POST', { quiz_id })
export const reviewWrongs = (keys: string[]) => api<Session>('/api/v1/attempts/review', 'POST', { keys })
export async function uploadAvatar(filePath: string) {
  const session = credentials()
  try {
    const r = await Taro.uploadFile({ url: API_BASE + '/api/v1/me/avatar', filePath, name: 'file', header: { Authorization: `Bearer ${session.token}` } })
    return unwrap<User>({ statusCode: r.statusCode, data: JSON.parse(r.data) }, session)
  } catch (e) {
    if (e instanceof ApiError) throw e
    throw new ApiError('头像暂时无法上传，请重试')
  }
}
export async function downloadAvatar() {
  const session = credentials()
  const r = await Taro.downloadFile({ url: API_BASE + '/api/v1/me/avatar', header: { Authorization: `Bearer ${session.token}` }, ...(process.env.TARO_ENV === 'h5' ? { withCredentials: false } : {}) })
  if (session.epoch !== credentials().epoch) throw new ApiError('账号已切换', 'SESSION_CHANGED')
  if (r.statusCode === 401) clearCredentials()
  if (r.statusCode !== 200) throw new ApiError('头像暂时无法读取')
  return r.tempFilePath
}
