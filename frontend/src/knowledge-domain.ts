import type { Grounding, EvidenceSegment, ScopeCandidate } from './grounding-domain'

export type KnowledgeFormat = 'pdf' | 'docx' | 'txt' | 'md' | 'markdown' | 'web'
export type KnowledgeJobType = 'import' | 'reindex' | 'question' | 'prepare' | 'quiz'
export type KnowledgeJobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export interface KnowledgeDocument {
  id: string; title: string; source_type: KnowledgeFormat; source: { filename?: string; url?: string; retrieved_at?: string; truncated?: boolean }
  status: 'processing' | 'ready' | 'failed' | 'cancelled' | 'deleted'; active_revision_id: string | null
  version: number | null; text_chars: number; chunk_count: number; job_id?: string | null
  error_code?: string | null; message?: string | null; created_at: string; updated_at: string
}
export interface KnowledgeSelection {
  document_ids?: string[]; all_ready?: boolean; supplement: boolean
}
export interface KnowledgeDocumentSnapshot { id: string; revision_id: string; version: number; title: string; source_type: KnowledgeFormat; deleted?: boolean; version_changed?: boolean }
export interface KnowledgeJob {
  kind: 'knowledge_job'; id: string; job_id: string; job_type: KnowledgeJobType; document_id?: string | null
  status: KnowledgeJobStatus; stage: string; progress: number; error_code?: string | null; message?: string | null
  retry_after_seconds: number; deadline: string; created_at: string; result?: unknown
}
export interface KnowledgePage<T> { items: T[]; total: number; page: number; page_size: number }
export interface KnowledgeChunk { id: string; revision_id: string; position: number; text: string; location: { page?: number; block?: number; header_path?: string[]; start_index: number; end_index: number; line_start?: number; line_end?: number } }
export interface KnowledgeCapabilities {
  enabled: boolean; available: boolean; embedding_available: boolean; web_available: boolean; reason_code?: string | null
  worker: { status: string; heartbeat_at: string | null }; formats: string[]
  limits: { max_bytes: number; max_documents: number; question_max_chars: number }; disclosure: string
}
export interface KnowledgeScope {
  kind: 'knowledge_scope'; id: string; version: number; goal: string; input_text: string
  documents: KnowledgeDocumentSnapshot[]; supplement: boolean; status: 'ready'; content: { candidates: ScopeCandidate[] }
  evidence: EvidenceSegment[]; grounding: Grounding | null; recommended_candidate_ids: string[]; created_at: string; expires_at: string
}
export interface KnowledgeQuizSelection {
  scope_id: string; scope_version: number; candidate_ids: string[]; question_count: 3 | 5; difficulty: 'easy' | 'medium'; supplement: boolean
}
export interface KnowledgeAnswer {
  kind: 'knowledge_answer'; id: string; question: string; documents: KnowledgeDocumentSnapshot[]; supplement: boolean
  status: 'answered' | 'insufficient'; paragraphs: { id: string; text: string; source_ids: string[] }[]
  sources: EvidenceSegment[]; grounding: Grounding | null; conflicts: { source_ids: string[]; message: string }[]
  message?: string | null; reason_code?: string | null; network: { requested: boolean; status: string; reason_code?: string | null }; created_at: string
}
export interface KnowledgeAnswerSummary { id: string; question: string; status: 'answered' | 'insufficient'; answer_preview: string; message?: string | null; created_at: string }
export interface KnowledgeMaterialChoice { id: string; title: string; source_type: KnowledgeFormat; created_at: string }
export interface KnowledgeTask {
  uid: string; key: string; job_type: KnowledgeJobType; id?: string; title: string; saved_at: number; progress: number
  input?: Record<string, unknown>
}
export const terminalKnowledgeJob = (value: KnowledgeJob) => ['succeeded', 'failed', 'cancelled'].includes(value.status)
export function isKnowledgeJob(value: unknown): value is KnowledgeJob {
  const v = value as KnowledgeJob | undefined
  return !!v && v.kind === 'knowledge_job' && typeof v.id === 'string' && v.id.length > 0 && v.job_id === v.id &&
    ['import', 'reindex', 'question', 'prepare', 'quiz'].includes(v.job_type) &&
    ['queued', 'running', 'succeeded', 'failed', 'cancelled'].includes(v.status) &&
    typeof v.stage === 'string' && Number.isInteger(v.progress) && v.progress >= 0 && v.progress <= 100 &&
    (v.status === 'succeeded' ? v.progress === 100 : v.progress < 100) && typeof v.deadline === 'string'
}
export function mergeKnowledgeProgress(previous: KnowledgeJob | undefined, next: KnowledgeJob): KnowledgeJob {
  if (!previous || previous.id !== next.id) return next
  if (terminalKnowledgeJob(previous)) return previous
  return { ...next, progress: Math.max(previous.progress, next.progress) }
}
export function knowledgeFileProblem(name: string, size: number) {
  if (!/\.(pdf|docx|txt|md|markdown)$/i.test(name)) return '请选择文字 PDF、Word（DOCX）、Markdown 或 TXT；暂不支持旧 DOC 和扫描件。'
  if (!size || size > 20 * 1024 * 1024) return '请选择非空且不超过 20 MB 的文件。'
  return ''
}
export const knowledgeStage = (stage: string) => ({ queued: '正在排队', starting: '开始处理', parsing: '正在读取文档', parsed: '原文已保存', split: '分块已完成', embedding: '正在建立资料索引', retrieving: '正在检索所选资料', retrieved: '依据已准备', planning: '正在规划资料获取', searching: '正在搜索公开资料', extracting: '正在读取公开网页', summarizing: '正在整理学习主题', scope_ready: '范围已整理', answering: '正在生成回答', checking_answer: '正在核对回答依据', generating: '正在准备题目', reviewing: '正在审核题目', publishing: '正在保存结果', waiting_ai: '正在等待学习服务额度', succeeded: '处理完成', failed: '本次处理未完成', cancelled: '已取消处理' })[stage] || '正在处理'
export const knowledgeStatus = (status: KnowledgeDocument['status']) => ({ ready: '已就绪', processing: '处理中', failed: '处理失败', cancelled: '已取消', deleted: '已删除' })[status]
export const knowledgeUnavailable = (code?: string | null) => ({ KNOWLEDGE_DISABLED: '个人知识库尚未启用，现有学习功能可继续使用。', EMBEDDING_NOT_CONFIGURED: '资料处理服务尚未配置，请完成服务配置后再添加资料。', KNOWLEDGE_WORKER_UNAVAILABLE: '知识库处理服务暂未运行，请稍后重试。', KNOWLEDGE_MIGRATION_REQUIRED: '知识库数据服务需要更新，请完成更新后重试。', KNOWLEDGE_CONFIGURATION_INVALID: '知识库配置需要检查，现有学习功能可继续使用。', KNOWLEDGE_DEPENDENCY_UNAVAILABLE: '知识库处理服务尚未就绪，请稍后重试。' })[code || ''] || '知识库服务暂未就绪，请稍后重试。'
