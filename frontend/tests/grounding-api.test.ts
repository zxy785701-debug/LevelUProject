import { beforeEach, expect, it, vi } from 'vitest'
const taro = vi.hoisted(() => ({ request: vi.fn(), getStorageSync: vi.fn(), setStorageSync: vi.fn(), removeStorageSync: vi.fn() }))
vi.mock('@tarojs/taro', () => ({ default: taro }))
import { api, RequestScope } from '../src/api'
import { credentials, saveCredentials } from '../src/credentials'
import { submitGeneration, pollGeneration, generateConfirmed, pollDelay, generationPollDelay, savePendingStudy, getPendingStudy, operationError } from '../src/grounding-api'
import { isGenerationOperation, isSession, splitTopicInput, groundingLabel } from '../src/grounding-domain'

it('出题和审核每秒查结果，但尊重限流等待，避免完成后额外等待五秒', () => {
  expect(generationPollDelay(100, { status: 'running', stage: 'reviewing' })).toBe(1000)
  expect(generationPollDelay(100, { status: 'running', stage: 'generating' })).toBe(1000)
  expect(generationPollDelay(100, { status: 'running', stage: 'waiting_rate_limit', retry_after_seconds: 12 })).toBe(12000)
  expect(generationPollDelay(100, { status: 'running', stage: 'generating', retry_after_seconds: 12 })).toBe(12000)
})

const body = { preparation_id: 'p', scope_version: 1, candidate_id: 'c', focus_id: 'f', scope_point_ids: ['point'], question_count: 3 as const, difficulty: 'easy' as const }

it('模型故障有明确原因，轮询失败也向页面传递具体提示', async () => {
  expect(operationError('MODEL_UNAVAILABLE')).toContain('无法连接 AI 模型服务')
  expect(operationError('MODEL_TIMEOUT')).toContain('响应超时')
  expect(operationError('MODEL_RATE_LIMIT')).toContain('服务繁忙')
  taro.request.mockResolvedValue(response({ status: 'failed', error_code: 'MODEL_UNAVAILABLE' }))
  await expect(pollGeneration('failed-model', new RequestScope(), () => {})).rejects.toMatchObject({
    code: 'MODEL_UNAVAILABLE', message: operationError('MODEL_UNAVAILABLE'),
  })
})
const session = { id: 'session', quiz: { id: 'quiz', questions: [] }, answers: [] }
const response = (data: unknown) => ({ statusCode: 200, data: { code: 0, data } })
beforeEach(() => { vi.clearAllMocks(); vi.stubGlobal('API_BASE', 'http://test'); saveCredentials('token') })

it('按操作取消，只终止本操作的 Taro RequestTask', async () => {
  const pending: { resolve: (value: unknown) => void; abort: ReturnType<typeof vi.fn> }[] = []
  taro.request.mockImplementation(() => {
    let resolve!: (value: unknown) => void, reject!: (reason: unknown) => void
    const promise = new Promise((yes, no) => { resolve = yes; reject = no })
    const abort = vi.fn(() => reject(new Error('request aborted')))
    pending.push({ resolve, abort })
    return Object.assign(promise, { abort })
  })
  const firstScope = new RequestScope(), secondScope = new RequestScope()
  const first = api('/first', 'GET', undefined, undefined, { scope: firstScope })
  const second = api('/second', 'GET', undefined, undefined, { scope: secondScope })
  const rejection = expect(first).rejects.toMatchObject({ code: 'REQUEST_CANCELLED' })
  firstScope.cancel()
  pending[1].resolve(response({ id: 'second' }))
  await rejection
  expect(await second).toEqual({ id: 'second' })
  expect(pending[0].abort).toHaveBeenCalledOnce()
  expect(pending[1].abort).not.toHaveBeenCalled()
})

it('旧账号迟到的 401 不清除新账号，并拒绝旧回包', async () => {
  let resolve!: (value: unknown) => void
  taro.request.mockReturnValue(Object.assign(new Promise(yes => { resolve = yes }), { abort: vi.fn() }))
  const promise = api('/old', 'GET', undefined, undefined, { scope: new RequestScope() })
  saveCredentials('new-account')
  resolve({ statusCode: 401, data: { code: 'AUTH_REQUIRED', message: 'old auth' } })
  await expect(promise).rejects.toMatchObject({ code: 'SESSION_CHANGED' })
  expect(credentials().token).toBe('new-account')
})
it('切换选择后旧操作的迟到成功回包被拒绝', async () => {
  let resolve!: (value: unknown) => void
  const abort = vi.fn()
  taro.request.mockReturnValue(Object.assign(new Promise(yes => { resolve = yes }), { abort }))
  const oldSelection = new RequestScope()
  const pending = api('/old-selection', 'GET', undefined, undefined, { scope: oldSelection })
  const rejected = expect(pending).rejects.toMatchObject({ code: 'REQUEST_CANCELLED' })
  oldSelection.cancel()
  resolve(response(session))
  await rejected
  expect(abort).toHaveBeenCalledOnce()
})

it('后台操作不能当 Session，Session 也不能当操作', async () => {
  expect(isSession({ kind: 'generation_operation', key: 'key', status: 'running' })).toBe(false)
  expect(isGenerationOperation(session)).toBe(false)
  taro.request.mockResolvedValue(response(session))
  await expect(submitGeneration(body, 'key', new RequestScope())).rejects.toMatchObject({ code: 'INVALID_OPERATION_RESPONSE' })
})

it('限流等待采用服务端时间和有限退避，成功后才返回 Session', async () => {
  const deadline = new Date(Date.now() + 300000).toISOString()
  taro.request.mockResolvedValueOnce(response({ status: 'running', stage: 'waiting_rate_limit', retry_after_seconds: 30, deadline }))
    .mockResolvedValueOnce(response({ status: 'running', stage: 'reviewing', deadline }))
    .mockResolvedValueOnce(response({ status: 'succeeded', stage: 'succeeded', result: session, deadline }))
  const scope = new RequestScope(), updates: string[] = []
  const sleep = vi.spyOn(scope, 'sleep').mockResolvedValue()
  const result = await pollGeneration('same-key', scope, value => updates.push(value.stage!))
  expect(result.id).toBe('session')
  expect(updates).toEqual(['waiting_rate_limit', 'reviewing', 'succeeded'])
  expect(sleep.mock.calls.map(([ms]) => ms)).toEqual([15000, 1000])
  expect(taro.request.mock.calls.every(([options]) => options.url.endsWith('/same-key') && options.timeout === 15000)).toBe(true)
  expect(pollDelay(200)).toBe(5000)
})

it('断网后重试沿用原生成键，不创建不同操作', async () => {
  const deadline = new Date(Date.now() + 300000).toISOString()
  taro.request.mockRejectedValueOnce(new Error('connection lost'))
    .mockResolvedValueOnce(response({ kind: 'generation_operation', key: 'original', status: 'running', stage: 'generating', deadline }))
    .mockResolvedValueOnce(response({ status: 'succeeded', result: session, deadline }))
  await expect(generateConfirmed(body, 'original', new RequestScope(), () => {})).rejects.toMatchObject({ code: 'NETWORK_ERROR' })
  expect((await generateConfirmed(body, 'original', new RequestScope(), () => {})).id).toBe('session')
  const submissions = taro.request.mock.calls.filter(([options]) => options.method === 'POST')
  expect(submissions.map(([options]) => options.header['Idempotency-Key'])).toEqual(['original', 'original'])
})

it('持续断网的轮询有限停止并保留原操作', async () => {
  taro.request.mockRejectedValue(new Error('offline'))
  const scope = new RequestScope()
  vi.spyOn(scope, 'sleep').mockResolvedValue()
  await expect(pollGeneration('original', scope, () => {})).rejects.toMatchObject({ code: 'NETWORK_ERROR' })
  expect(taro.request).toHaveBeenCalledTimes(4)
})

it('取消查询也能中断轮询等待', async () => {
  vi.useFakeTimers()
  try {
    const scope = new RequestScope()
    const sleep = scope.sleep(15000)
    const rejection = expect(sleep).rejects.toMatchObject({ code: 'REQUEST_CANCELLED' })
    scope.cancel()
    await rejection
    expect(vi.getTimerCount()).toBe(0)
  } finally { vi.useRealTimers() }
})

it('待恢复记录按账号存储，网址说明不丢失，旧状态不误标', () => {
  const value = { kind: 'generation' as const, key: 'key', body, saved_at: 1 }
  savePendingStudy('alice', value)
  expect(taro.setStorageSync).toHaveBeenLastCalledWith('levelup.grounding.alice', value)
  taro.getStorageSync.mockImplementation(key => key === 'levelup.grounding.alice' ? value : undefined)
  expect(getPendingStudy('bob')).toBeUndefined()
  expect(splitTopicInput('https://example.com/doc 重点学习应用案例')).toEqual({ url: 'https://example.com/doc', instruction: '重点学习应用案例' })
  expect(groundingLabel()).toBe('未记录核实状态')
})
