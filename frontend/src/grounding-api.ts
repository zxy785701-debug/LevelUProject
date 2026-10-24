import Taro from '@tarojs/taro'
import { api, ApiError, RequestScope } from './api'
import { GenerationBody, GenerationOperation, MaterialEntryHint, OperationResult, PendingStudy, Preparation, isGenerationOperation, isSession } from './grounding-domain'
import type { Session } from './domain'

export const prepareTopic = (text: string, key: string, scope?: RequestScope) => api<Preparation | MaterialEntryHint>('/api/v1/quiz/preparations', 'POST', { text }, key, { scope, timeout: 15000 })
export const getPreparation = (id: string, scope?: RequestScope) => api<Preparation>('/api/v1/quiz/preparations/' + encodeURIComponent(id), 'GET', undefined, undefined, { scope, timeout: 15000 })
export const cancelPreparation = (id: string) => api<Preparation>('/api/v1/quiz/preparations/' + encodeURIComponent(id) + '/cancel', 'POST', undefined, undefined, { timeout: 15000 })
export async function submitGeneration(body: GenerationBody, key: string, scope?: RequestScope): Promise<GenerationOperation> {
  const result = await api<unknown>('/api/v1/quiz/generate', 'POST', body, key, { scope, timeout: 15000 })
  if (!isGenerationOperation(result)) throw new ApiError('出题操作返回格式不完整，请查询原操作', 'INVALID_OPERATION_RESPONSE')
  return result
}
export const getOperation = (key: string, scope?: RequestScope) => api<OperationResult>('/api/v1/operations/' + encodeURIComponent(key), 'GET', undefined, undefined, { scope, timeout: 15000 })
export const pollDelay = (attempt: number, retry = 0) => retry > 0 ? Math.min(15000, Math.max(1000, retry * 1000)) : Math.min(5000, Math.round(750 * 1.5 ** Math.min(attempt, 8)))
export const generationPollDelay = (attempt: number, value: OperationResult) =>
  !value.retry_after_seconds && ['generating', 'reviewing', 'generating_images'].includes(value.stage || '') ? 1000 : pollDelay(attempt, value.retry_after_seconds)
export const operationError = (code?: string | null) => ({
  MODEL_UNAVAILABLE: '暂时无法连接 AI 模型服务，请稍后重试；输入已保留',
  MODEL_TIMEOUT: 'AI 模型响应超时，请稍后重试；输入已保留',
  MODEL_RATE_LIMIT: 'AI 模型服务繁忙，请稍后重试',
  MODEL_INVALID_OUTPUT: 'AI 返回的内容未通过校验，请重新尝试',
  MODEL_TOOL_PARAMETERS_INVALID: 'AI 未能正确选择检索参数，请重新尝试',
  PREPARATION_FAILED: '学习范围整理失败，请重新尝试或补充学习目标',
  NO_READABLE_CONTENT: '未能读取到材料正文，请粘贴正文或换一个可访问的网址',
  OPERATION_CANCELLED: '操作已取消，可以重新准备',
 PREPARATION_EXPIRED: '学习范围已过期，请重新准备', OPERATION_EXPIRED: '操作中断或超时，请重新发起', OPERATION_INTERRUPTED: '操作中断，请重新发起', SCOPE_CONFIRMATION_REQUIRED: '请先确认学习范围', SCOPE_VERSION_MISMATCH: '学习范围已变化，请重新确认', INVALID_SCOPE_SELECTION: '请选择当前范围中的方向和知识点', INSUFFICIENT_KNOWLEDGE: '该范围资料不足，请缩小范围或补充资料', QUIZ_REVIEW_FAILED: '题目依据未通过审核，请补充资料后重试', DAILY_QUOTA_EXCEEDED: '今天的出题额度已用完，明天再来', TOPIC_PREPARE_DAILY_LIMIT: '今天的主题准备次数已用完', AI_RATE_LIMIT: '暂时无法完成额度等待，请稍后再试', MODEL_BUDGET_EXHAUSTED: '本次调用预算已用完，请缩小范围重试', MODEL_NOT_CONFIGURED: '模型暂未配置，请稍后再试', MODEL_AUTH_ERROR: '模型服务认证失败，请联系维护者', MODEL_TOOL_CALL_UNSUPPORTED: '当前模型暂不支持资料工具，请联系维护者', GROUNDING_DISABLED: '新出题功能暂时关闭，请稍后再试' })[code || ''] || '本次操作未完成，请保留输入后重试'

export async function pollPreparation(id: string, scope: RequestScope, update: (value: Preparation) => void): Promise<Preparation> {
  const until = Date.now() + 255000
  for (let attempt = 0, errors = 0; attempt < 120 && Date.now() < until; attempt++) {
    scope.assertCurrent()
    let value: Preparation
    try { value = await getPreparation(id, scope); errors = 0 }
    catch (e) { if (!(e instanceof ApiError) || e.code !== 'NETWORK_ERROR' || ++errors > 3) throw e; await scope.sleep(pollDelay(attempt)); continue }
    update(value)
    if (value.status !== 'running') return value
    await scope.sleep(pollDelay(attempt, value.retry_after_seconds))
  }
  throw new ApiError('查询暂未结束，任务仍可通过原操作恢复', 'QUERY_PENDING')
}
export async function pollGeneration(key: string, scope: RequestScope, update: (value: OperationResult) => void, withImages = false): Promise<Session> {
  let until = Date.now() + 330000 + (withImages ? 180000 : 0)
  for (let attempt = 0, errors = 0; attempt < 510 && Date.now() < until; attempt++) {
    scope.assertCurrent()
    let value: OperationResult
    try { value = await getOperation(key, scope); errors = 0 }
    catch (e) { if (!(e instanceof ApiError) || e.code !== 'NETWORK_ERROR' || ++errors > 3) throw e; await scope.sleep(pollDelay(attempt)); continue }
    update(value)
    if (value.deadline) until = Math.min(until, Date.parse(value.deadline) + 15000)
    if (value.status === 'failed') throw new ApiError(operationError(value.error_code), value.error_code || 'OPERATION_FAILED')
    if (value.status === 'succeeded') {
      if (!isSession(value.result)) throw new ApiError('学习结果暂时无法读取，请查询原操作', 'INVALID_SESSION_RESPONSE')
      return value.result
    }
    await scope.sleep(generationPollDelay(attempt, value))
  }
  throw new ApiError('查询暂未结束，请稍后恢复原操作', 'QUERY_PENDING')
}
export async function generateConfirmed(body: GenerationBody, key: string, scope: RequestScope, update: (value: OperationResult) => void) {
  await submitGeneration(body, key, scope)
  return pollGeneration(key, scope, update, body.generate_images === true)
}
const pendingKey = (uid: string) => 'levelup.grounding.' + uid
export function savePendingStudy(uid: string, value: PendingStudy) { Taro.setStorageSync(pendingKey(uid), value) }
export function getPendingStudy(uid: string): PendingStudy | undefined { try { const value = Taro.getStorageSync(pendingKey(uid)); if (value && ['preparation', 'generation'].includes(value.kind) && typeof value.key === 'string') return value } catch {} }
export function clearPendingStudy(uid: string) { Taro.removeStorageSync(pendingKey(uid)) }
