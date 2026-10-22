import Taro from '@tarojs/taro'
import { api, ApiError, RequestScope, unwrap } from './api'
import { credentials } from './credentials'
import type { DocumentFile } from './features-api'
import { isKnowledgeJob, knowledgeFileProblem } from './knowledge-domain'
import type { KnowledgeJob, KnowledgeJobType, KnowledgePage, KnowledgeDocument, KnowledgeChunk, KnowledgeCapabilities, KnowledgeSelection, KnowledgeScope, KnowledgeQuizSelection, KnowledgeAnswer, KnowledgeAnswerSummary, KnowledgeMaterialChoice } from './knowledge-domain'

const base = '/api/v1/knowledge'
const control = (scope?: RequestScope) => ({ scope, timeout: 15000 })
function job(value: unknown): KnowledgeJob {
  if (!isKnowledgeJob(value)) throw new ApiError('任务状态暂时无法确认，请恢复原提交。', 'INVALID_KNOWLEDGE_JOB')
  return value
}
async function postJob(path: string, data: unknown, key: string, scope?: RequestScope) { return job(await api<unknown>(base + path, 'POST', data, key, control(scope))) }
export const knowledgeCapabilities = (scope?: RequestScope) => api<KnowledgeCapabilities>(base + '/capabilities', 'GET', undefined, undefined, control(scope))
export const listKnowledgeDocuments = (page = 1, scope?: RequestScope) => api<KnowledgePage<KnowledgeDocument>>(base + '/documents?page=' + page + '&page_size=100', 'GET', undefined, undefined, control(scope))
export const getKnowledgeDocument = (id: string, scope?: RequestScope) => api<KnowledgeDocument>(base + '/documents/' + encodeURIComponent(id), 'GET', undefined, undefined, control(scope))
export const getKnowledgeChunks = (id: string, page = 1, scope?: RequestScope) => api<KnowledgePage<KnowledgeChunk>>(base + '/documents/' + encodeURIComponent(id) + '/chunks?page=' + page, 'GET', undefined, undefined, control(scope))
export const knowledgeMaterials = (page = 1, scope?: RequestScope) => api<KnowledgePage<KnowledgeMaterialChoice>>(base + '/materials?page=' + page, 'GET', undefined, undefined, control(scope))
export const importKnowledgeWeb = (url: string, key: string, scope?: RequestScope) => postJob('/documents/web', { url }, key, scope)
export const copyKnowledgeMaterial = (material_id: string, key: string, scope?: RequestScope) => postJob('/documents/from-material', { material_id }, key, scope)
export const reindexKnowledge = (id: string, key: string, scope?: RequestScope) => postJob('/documents/' + encodeURIComponent(id) + '/reindex', {}, key, scope)
export const deleteKnowledge = (id: string, scope?: RequestScope) => api<{ deleted: boolean; cleanup?: { kind: 'knowledge_cleanup'; id: string; status: string } }>(base + '/documents/' + encodeURIComponent(id), 'DELETE', undefined, undefined, control(scope))
export async function getKnowledgeJob(id: string, scope?: RequestScope) { return job(await api<unknown>(base + '/jobs/' + encodeURIComponent(id), 'GET', undefined, undefined, control(scope))) }
export async function lookupKnowledgeJob(kind: KnowledgeJobType, key: string, scope?: RequestScope) { return job(await api<unknown>(base + '/job-lookup?job_type=' + kind + '&key=' + encodeURIComponent(key), 'GET', undefined, undefined, control(scope))) }
export const cancelKnowledgeJob = (id: string, scope?: RequestScope) => postJob('/jobs/' + encodeURIComponent(id) + '/cancel', {}, '', scope)
export const retryKnowledgeJob = (id: string, key: string, scope?: RequestScope) => postJob('/jobs/' + encodeURIComponent(id) + '/retry', {}, key, scope)
export const askKnowledge = (question: string, selection: KnowledgeSelection, key: string, scope?: RequestScope) => postJob('/questions', { question, ...selection }, key, scope)
export const prepareKnowledgeQuiz = (goal: string, selection: KnowledgeSelection, key: string, scope?: RequestScope) => postJob('/quiz-preparations', { goal, ...selection }, key, scope)
export const getKnowledgeScope = (id: string, scope?: RequestScope) => api<KnowledgeScope>(base + '/quiz-preparations/' + encodeURIComponent(id), 'GET', undefined, undefined, control(scope))
export const generateKnowledgeQuiz = (selection: KnowledgeQuizSelection, key: string, scope?: RequestScope) => postJob('/quizzes', selection, key, scope)
export const listKnowledgeAnswers = (page = 1, scope?: RequestScope) => api<KnowledgePage<KnowledgeAnswerSummary>>(base + '/questions?page=' + page, 'GET', undefined, undefined, control(scope))
export const getKnowledgeAnswer = (id: string, scope?: RequestScope) => api<KnowledgeAnswer>(base + '/questions/' + encodeURIComponent(id), 'GET', undefined, undefined, control(scope))
export const deleteKnowledgeAnswer = (id: string, scope?: RequestScope) => api<{ deleted: boolean }>(base + '/questions/' + encodeURIComponent(id), 'DELETE', undefined, undefined, control(scope))
export const knowledgeQuizContext = (id: string, scope?: RequestScope) => api<{ goal: string; documents: KnowledgeScope['documents']; supplement: boolean; requires_confirmation: true }>(base + '/questions/' + encodeURIComponent(id) + '/quiz-context', 'GET', undefined, undefined, control(scope))

export async function chooseKnowledgeDocument(): Promise<DocumentFile> {
  if (process.env.TARO_ENV !== 'h5') {
    try {
      // Taro 4.3 delegates this API to wx; some runtimes only return via callbacks.
      const result = await new Promise<Taro.chooseMessageFile.SuccessCallbackResult>((resolve, reject) => {
        const pending = Taro.chooseMessageFile({ count: 1, type: 'file', extension: ['pdf', 'docx', 'txt', 'md', 'markdown'], success: resolve, fail: reject })
        // Also observe a Promise when supplied, so failures never become unhandled.
        if (pending && typeof pending.then === 'function') pending.then(resolve, reject)
      })
      if (!result.tempFiles[0]) throw new ApiError('已取消选择', 'FILE_SELECTION_CANCELLED')
      return result.tempFiles[0]
    } catch (error) {
      if (error instanceof ApiError) throw error
      const reason = String((error as { errMsg?: string })?.errMsg || '')
      if (/cancel/i.test(reason)) throw new ApiError('已取消选择', 'FILE_SELECTION_CANCELLED')
      if (/The ["']fd["'] argument must be of type number/i.test(reason)) throw new ApiError('微信开发者工具无法打开文件窗口，请完全退出后重新打开；若仍失败，请更新开发者工具。', 'FILE_PICKER_UNAVAILABLE')
      throw new ApiError('暂时无法选择文件，请重新选择或稍后重试。', 'FILE_SELECTION_FAILED')
    }
  }
  return new Promise((resolve, reject) => {
    const input = document.createElement('input')
    input.type = 'file'; input.accept = '.pdf,.docx,.txt,.md,.markdown'; input.style.display = 'none'
    document.body.appendChild(input)
    input.onchange = () => { const file = input.files?.[0]; input.remove(); if (file) resolve({ name: file.name, path: URL.createObjectURL(file), size: file.size }); else reject(new ApiError('已取消选择', 'FILE_SELECTION_CANCELLED')) }
    input.oncancel = () => { input.remove(); reject(new ApiError('已取消选择', 'FILE_SELECTION_CANCELLED')) }
    input.click()
  })
}
export async function uploadKnowledgeDocument(file: DocumentFile, key: string, scope?: RequestScope, onProgress?: (value: number) => void): Promise<KnowledgeJob> {
  const problem = knowledgeFileProblem(file.name, file.size)
  if (problem) throw new ApiError(problem, 'INVALID_KNOWLEDGE_FILE')
  const session = credentials()
  let task: ReturnType<typeof Taro.uploadFile> | undefined
  let progress = 0
  try {
    scope?.assertCurrent()
    task = Taro.uploadFile({ url: API_BASE + base + '/documents/upload', filePath: file.path, fileName: file.name, name: 'file', timeout: 120000,
      ...(process.env.TARO_ENV === 'h5' ? { withCredentials: false } : {}),
      header: { Authorization: `Bearer ${session.token}`, 'Idempotency-Key': key } })
    scope?.track(task)
    if (onProgress && typeof task.onProgressUpdate === 'function') task.onProgressUpdate(event => {
      try { scope?.assertCurrent(); if (session.epoch === credentials().epoch && Number.isFinite(event.progress)) { progress = Math.max(progress, Math.min(99, Math.max(0, event.progress))); onProgress(progress) } } catch {}
    })
    const response = await task
    scope?.assertCurrent()
    let data: unknown
    try { data = typeof response.data === 'string' ? JSON.parse(response.data) : response.data }
    catch { throw new ApiError('上传结果暂时无法确认，请恢复原提交。', 'INVALID_KNOWLEDGE_JOB') }
    return job(unwrap<unknown>({ statusCode: response.statusCode, data }, session))
  } catch (error) {
    if (error instanceof ApiError) throw error
    scope?.assertCurrent()
    throw new ApiError('上传连接中断，请先恢复原提交或刷新资料列表，再重新选择文件。')
  } finally { if (task) scope?.release(task) }
}
