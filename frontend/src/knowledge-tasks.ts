import Taro from '@tarojs/taro'
import { ApiError, RequestScope } from './api'
import { getKnowledgeJob } from './knowledge-api'
import { isKnowledgeJob, mergeKnowledgeProgress, terminalKnowledgeJob } from './knowledge-domain'
import type { KnowledgeJob, KnowledgeTask } from './knowledge-domain'

const storageKey = (uid: string) => 'levelup.knowledge.tasks.v1:' + uid
export function loadKnowledgeTasks(uid: string): KnowledgeTask[] {
  try {
    const values = Taro.getStorageSync(storageKey(uid))
    if (!Array.isArray(values)) return []
    return values.filter((v: KnowledgeTask) => v?.uid === uid && typeof v.key === 'string' && v.key.length > 0 && v.key.length <= 128 && typeof v.title === 'string' &&
      (v.id === undefined || typeof v.id === 'string' && v.id.length > 0) && Number.isInteger(v.progress) && v.progress >= 0 && v.progress <= 100 &&
      ['import', 'reindex', 'question', 'prepare', 'quiz'].includes(v.job_type) && Number.isFinite(v.saved_at)).slice(-20)
  } catch { return [] }
}
export function saveKnowledgeTask(uid: string, value: KnowledgeTask) {
  if (value.uid !== uid) throw new ApiError('账号已切换，请恢复当前账号的任务。', 'SESSION_CHANGED')
  const values = loadKnowledgeTasks(uid).filter(v => v.key !== value.key)
  Taro.setStorageSync(storageKey(uid), [...values, value].slice(-20))
}
export function clearKnowledgeTask(uid: string, key: string) { Taro.setStorageSync(storageKey(uid), loadKnowledgeTasks(uid).filter(v => v.key !== key)) }
export class KnowledgeTaskWatcher {
  private ticket = 0
  private scope?: RequestScope
  private previous?: KnowledgeJob
  constructor(private uid: string, private notify: (value: KnowledgeJob) => void, private options?: { load?: typeof getKnowledgeJob; interval?: number }) {}
  pause() { this.ticket++; this.scope?.cancel(); this.scope = undefined }
  async watch(task: KnowledgeTask): Promise<KnowledgeJob | undefined> {
    if (task.uid !== this.uid || !task.id) throw new ApiError('请选择当前账号已提交的任务。', 'INVALID_KNOWLEDGE_TASK')
    this.pause()
    const ticket = this.ticket, scope = this.scope = new RequestScope()
    const started = Date.now()
    let errors = 0
    try {
      while (Date.now() - started < 16 * 60 * 1000) {
        let next: KnowledgeJob
        try { next = await (this.options?.load || getKnowledgeJob)(task.id, scope); errors = 0 }
        catch (error) {
          if (error instanceof ApiError && error.code === 'NETWORK_ERROR' && ++errors <= 3) { await scope.sleep(3000); continue }
          throw error
        }
        scope.assertCurrent()
        if (ticket !== this.ticket) return
        if (!isKnowledgeJob(next) || next.id !== task.id || next.job_type !== task.job_type) throw new ApiError('任务状态与原提交不一致，请恢复原提交。', 'INVALID_KNOWLEDGE_JOB')
        next = mergeKnowledgeProgress(this.previous, { ...next, progress: Math.max(Math.min(99, task.progress), next.progress) })
        this.previous = next
        saveKnowledgeTask(this.uid, { ...task, id: next.id, progress: next.progress })
        this.notify(next)
        if (terminalKnowledgeJob(next)) return next
        await scope.sleep(this.options?.interval ?? Math.min(5000, Math.max(2000, next.retry_after_seconds * 1000)))
      }
      throw new ApiError('查询暂未结束，后台任务仍在继续，可稍后恢复。', 'QUERY_PENDING')
    } catch (error) {
      if (error instanceof ApiError && ['REQUEST_CANCELLED', 'SESSION_CHANGED'].includes(error.code)) return
      throw error
    }
  }
}
