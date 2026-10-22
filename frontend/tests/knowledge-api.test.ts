import { beforeEach, expect, it, vi } from 'vitest'
const state = vi.hoisted(() => ({ storage: new Map<string, unknown>(), taro: { request: vi.fn(), uploadFile: vi.fn(), chooseMessageFile: vi.fn(), getStorageSync: vi.fn(), setStorageSync: vi.fn(), removeStorageSync: vi.fn() } }))
vi.mock('@tarojs/taro', () => ({ default: state.taro }))
import { RequestScope } from '../src/api'
import { saveCredentials, clearCredentials } from '../src/credentials'
import { askKnowledge, uploadKnowledgeDocument, chooseKnowledgeDocument, lookupKnowledgeJob } from '../src/knowledge-api'
import { isKnowledgeJob, mergeKnowledgeProgress, knowledgeFileProblem } from '../src/knowledge-domain'
import { loadKnowledgeTasks, saveKnowledgeTask, KnowledgeTaskWatcher } from '../src/knowledge-tasks'
import type { KnowledgeJob, KnowledgeTask } from '../src/knowledge-domain'

function job(progress = 0, status: KnowledgeJob['status'] = 'queued'): KnowledgeJob { return { kind: 'knowledge_job', id: 'j', job_id: 'j', job_type: 'import', stage: status, status, progress, deadline: new Date(Date.now() + 60000).toISOString(), created_at: new Date().toISOString(), retry_after_seconds: 0 } }
function response(value: unknown) { return { statusCode: 200, data: { code: 0, message: 'ok', data: value } } }
beforeEach(() => {
  vi.clearAllMocks(); state.storage.clear(); vi.stubGlobal('API_BASE', 'http://test')
  state.taro.getStorageSync.mockImplementation(key => state.storage.get(key))
  state.taro.setStorageSync.mockImplementation((key, value) => state.storage.set(key, value))
  state.taro.removeStorageSync.mockImplementation(key => state.storage.delete(key))
  saveCredentials('token-a')
  state.taro.request.mockResolvedValue(response(job()))
  state.taro.uploadFile.mockResolvedValue({ statusCode: 200, data: JSON.stringify(response(job()).data) })
})
it('任务身份和成功结果必须区别于旧材料任务及答题 Session', () => {
  expect(isKnowledgeJob(job())).toBe(true)
  expect(isKnowledgeJob({ id: 'session', quiz: { questions: [] }, answers: [] })).toBe(false)
  expect(isKnowledgeJob({ id: 'old-job', status: 'running' })).toBe(false)
  expect(isKnowledgeJob(job(100, 'running'))).toBe(false)
  expect(isKnowledgeJob(job(99, 'succeeded'))).toBe(false)
})
it('知识库提问使用明确范围和可见联网选择，短请求携带鉴权与原幂等键', async () => {
  const value = { ...job(), job_type: 'question' }
  state.taro.request.mockResolvedValue(response(value))
  await askKnowledge('原始问题', { document_ids: ['doc'], supplement: true }, 'question-key')
  expect(state.taro.request.mock.calls[0][0]).toMatchObject({ timeout: 15000, data: { question: '原始问题', document_ids: ['doc'], supplement: true }, header: { Authorization: 'Bearer token-a', 'Idempotency-Key': 'question-key' } })
  await lookupKnowledgeJob('question', 'question-key')
  expect(state.taro.request.mock.calls[1][0].url).toContain('/job-lookup?job_type=question&key=question-key')
})
it('原生上传解析字符串响应，支持 Markdown 并包含鉴权与幂等键', async () => {
  expect((await uploadKnowledgeDocument({ name: 'note.md', path: '/tmp/note.md', size: 20 }, 'key')).id).toBe('j')
  expect(state.taro.uploadFile.mock.calls[0][0]).toMatchObject({ name: 'file', fileName: 'note.md', header: { Authorization: 'Bearer token-a', 'Idempotency-Key': 'key' } })
  state.taro.chooseMessageFile.mockResolvedValue({ tempFiles: [{ name: 'note.markdown', path: 'tmp', size: 10 }] })
  await chooseKnowledgeDocument()
  expect(state.taro.chooseMessageFile.mock.calls[0][0].extension).toContain('markdown')
})
it('H5 上传不带 Cookie；旧账号的迟到响应不会影响新账号', async () => {
  vi.stubEnv('TARO_ENV', 'h5')
  await uploadKnowledgeDocument({ name: 'note.txt', path: 'blob:file', size: 20 }, 'key')
  expect(state.taro.uploadFile.mock.calls[0][0].withCredentials).toBe(false)
  state.taro.uploadFile.mockImplementation(async () => { saveCredentials('token-b'); return { statusCode: 401, data: '{"code":"AUTH_REQUIRED"}' } })
  await expect(uploadKnowledgeDocument({ name: 'note.txt', path: 'blob:file', size: 20 }, 'key')).rejects.toThrow('账号')
  vi.unstubAllEnvs()
})
it('上传可随本页查询停止，上传完成通知不能伪造索引已经完成', async () => {
  const abort = vi.fn(), progress = vi.fn()
  const task = Object.assign(Promise.resolve({ statusCode: 200, data: JSON.stringify(response(job()).data) }), { abort, onProgressUpdate: (cb: (value: { progress: number }) => void) => cb({ progress: 100 }) })
  state.taro.uploadFile.mockReturnValue(task)
  const scope = new RequestScope()
  const result = await uploadKnowledgeDocument({ name: 'note.txt', path: 'tmp', size: 20 }, 'key', scope, progress)
  expect(progress).toHaveBeenCalledWith(99)
  expect(result.status).toBe('queued')
  const scope2 = new RequestScope()
  let resolve!: (value: unknown) => void
  state.taro.uploadFile.mockReturnValue(Object.assign(new Promise(r => { resolve = r }), { abort }))
  const pending = uploadKnowledgeDocument({ name: 'note.txt', path: 'tmp', size: 20 }, 'key', scope2)
  scope2.cancel(); resolve({ statusCode: 200, data: JSON.stringify(response(job()).data) })
  await expect(pending).rejects.toThrow('停止')
  expect(abort).toHaveBeenCalledOnce()
})
it('错误上传响应和不支持文件不触发错误的关卡跳转', async () => {
  state.taro.uploadFile.mockResolvedValue({ statusCode: 200, data: '{bad' })
  await expect(uploadKnowledgeDocument({ name: 'note.txt', path: 'tmp', size: 20 }, 'key')).rejects.toThrow('确认')
  expect(knowledgeFileProblem('old.doc', 10)).toContain('DOCX')
  expect(knowledgeFileProblem('large.pdf', 21 * 1024 * 1024)).toContain('20 MB')
  state.taro.request.mockResolvedValue(response({ id: 'session', quiz: {}, answers: [] }))
  await expect(askKnowledge('问', { all_ready: true, supplement: false }, 'key')).rejects.toThrow('任务状态')
})
it('任务存储按账号隔离；进度和终态不会被迟到响应倒退', () => {
  const task: KnowledgeTask = { uid: 'alice', key: 'key', id: 'j', job_type: 'import', title: 'a.txt', saved_at: Date.now(), progress: 70 }
  saveKnowledgeTask('alice', task)
  expect(loadKnowledgeTasks('bob')).toEqual([])
  expect(() => saveKnowledgeTask('bob', task)).toThrow('账号')
  expect(mergeKnowledgeProgress(job(70, 'running'), job(20, 'running')).progress).toBe(70)
  expect(mergeKnowledgeProgress(job(100, 'succeeded'), job(50, 'running')).status).toBe('succeeded')
})
it('后台暂停只停止查询；恢复后沿用同一任务并保留单调进度', async () => {
  const onValue = vi.fn()
  let release!: (value: KnowledgeJob) => void
  const load = vi.fn().mockImplementationOnce(() => new Promise(r => { release = r })).mockResolvedValueOnce(job(100, 'succeeded'))
  const task: KnowledgeTask = { uid: 'alice', key: 'key', id: 'j', job_type: 'import', title: 'a.txt', saved_at: Date.now(), progress: 0 }
  const watcher = new KnowledgeTaskWatcher('alice', onValue, { load })
  const first = watcher.watch(task)
  watcher.pause(); release(job(70, 'running'))
  expect(await first).toBeUndefined(); expect(onValue).not.toHaveBeenCalled()
  expect((await watcher.watch(task))?.status).toBe('succeeded')
  expect(load.mock.calls.map(c => c[0])).toEqual(['j', 'j'])
  expect(state.taro.request.mock.calls.some(c => c[0].url.endsWith('/cancel'))).toBe(false)
})
it('账号切换后拒绝旧轮询结果', async () => {
  const onValue = vi.fn()
  let release!: (value: KnowledgeJob) => void
  const watcher = new KnowledgeTaskWatcher('alice', onValue, { load: vi.fn(() => new Promise<KnowledgeJob>(r => { release = r })) })
  const pending = watcher.watch({ uid: 'alice', id: 'j', key: 'key', job_type: 'import', title: 'a', saved_at: Date.now(), progress: 0 })
  clearCredentials(); saveCredentials('token-b'); release(job(100, 'succeeded'))
  expect(await pending).toBeUndefined(); expect(onValue).not.toHaveBeenCalled()
})
it('重新打开页面时以本机已确认的进度作为下限', async () => {
  const values: number[] = []
  const watcher = new KnowledgeTaskWatcher('alice', value => values.push(value.progress), { interval: 1, load: vi.fn().mockResolvedValueOnce(job(40, 'running')).mockResolvedValueOnce(job(100, 'succeeded')) })
  await watcher.watch({ uid: 'alice', id: 'j', key: 'restore', job_type: 'import', title: 'a', saved_at: Date.now(), progress: 70 })
  expect(values).toEqual([70, 100])
})
it('微信取消选择不会暴露原生错误，选择失败提供可恢复说明', async () => {
  state.taro.chooseMessageFile.mockRejectedValueOnce({ errMsg: 'chooseMessageFile:fail cancel' }).mockRejectedValueOnce({ errMsg: 'private device path' })
  await expect(chooseKnowledgeDocument()).rejects.toMatchObject({ code: 'FILE_SELECTION_CANCELLED' })
  await expect(chooseKnowledgeDocument()).rejects.toMatchObject({ code: 'FILE_SELECTION_FAILED', message: '暂时无法选择文件，请重新选择或稍后重试。' })
})
it('兼容只通过回调返回文件的微信运行时，不能把 undefined 返回值当作选择失败', async () => {
  const file = { name: 'callback.md', path: 'wxfile://temporary', size: 40 }
  let callbacks: any
  state.taro.chooseMessageFile.mockImplementationOnce(options => { callbacks = options; return undefined })
  const pending = chooseKnowledgeDocument()
  void pending.catch(() => {}) // Keep an early assertion failure from leaving a dangling rejection.
  expect(callbacks.success).toBeTypeOf('function')
  callbacks.success({ tempFiles: [file] })
  await expect(pending).resolves.toEqual(file)
})
it('开发者工具 fd 错误给出可执行的恢复提示，不暴露本地路径', async () => {
  state.taro.chooseMessageFile.mockRejectedValueOnce({ errMsg: 'chooseMessageFile:fail The "fd" argument must be of type number. Received undefined C:/private/path' })
  await expect(chooseKnowledgeDocument()).rejects.toMatchObject({ code: 'FILE_PICKER_UNAVAILABLE', message: '微信开发者工具无法打开文件窗口，请完全退出后重新打开；若仍失败，请更新开发者工具。' })
})
