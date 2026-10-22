import type { Session } from './domain'

export type VerificationState = 'source_backed' | 'unverified' | 'material_only'
export interface Grounding { status: VerificationState; reason_code?: string | null; retrieved_at?: string | null; provider?: 'tavily' | null; check_version?: string }
export interface EvidenceSegment {
  id: string; text: string; title?: string | null; url?: string | null; original_url?: string | null
  page?: number | null; start?: number | null; end?: number | null; supplement?: boolean
  content_kind?: 'snippet' | 'full_extract' | 'focused_extract' | 'material'
  retrieved_at?: string | null; published_at?: string | null; content_hash?: string | null
  acquisition_status?: 'available' | 'partial' | 'unknown'; truncated?: boolean; context_truncated?: boolean
  source_chars?: number | null; original_id?: string | null; original_quiz_id?: string | null
  knowledge?: { document_id: string; revision_id: string; chunk_id: string; document_title: string; source_type: string; document_version: number; chunk_position: number; header_path: string[]; start_index: number; end_index: number; block?: number | null; deleted?: boolean; version_changed?: boolean } | null
}
export interface QuizSource { type: string; title: string; material_id?: string | null; url?: string | null; segments: EvidenceSegment[] }
export interface LearningScope { input_text: string; topic: string; domain: string; focus: string; points: string[]; preparation_id?: string | null; scope_version?: number | null; candidate_id?: string | null; focus_id?: string | null; scope_point_ids?: string[] }
export interface Verification { status: VerificationState | 'unknown'; counts: Partial<Record<VerificationState | 'unknown', number>>; rule: string }
export interface ScopePoint { id: string; name: string; evidence_ids: string[]; evidence_status: 'available' | 'unverified' }
export interface ScopeFocus { id: string; name: string; description: string; points: ScopePoint[] }
export interface ScopeCandidate { id: string; topic: string; domain: string; description: string; focuses: ScopeFocus[] }
export type PreparationStatus = 'running' | 'ready' | 'failed' | 'cancelled' | 'expired'
export interface Preparation { id: string; version: number; input_text: string; status: PreparationStatus; stage: string; content?: { candidates: ScopeCandidate[] } | null; grounding?: Grounding | null; evidence: EvidenceSegment[]; error_code?: string | null; retry_after_seconds: number; created_at: string; expires_at: string }
export interface MaterialEntryHint { kind: 'material_entry'; url: string; learning_instruction?: string | null; message: string }
export interface TopicSelection { preparation_id: string; scope_version: number; candidate_ids?: string[]; candidate_id?: string; focus_id?: string; scope_point_ids?: string[]; question_count: 3 | 5; difficulty: 'easy' | 'medium' }
export interface MaterialSelection { material_id: string; point_ids: string[]; supplement: boolean; question_count: 3 | 5; difficulty: 'easy' | 'medium'; execution: 'background' }
export type GenerationBody = TopicSelection | MaterialSelection
export interface GenerationOperation { kind: 'generation_operation'; key: string; status: 'running' | 'succeeded' | 'failed'; stage: string; retry_after_seconds: number; deadline: string; error_code?: string | null }
export interface OperationResult { status: 'running' | 'succeeded' | 'failed'; stage?: string | null; retry_after_seconds?: number; deadline?: string | null; error_code?: string | null; result?: Session | null }
export type PendingStudy = { kind: 'preparation'; key: string; text: string; id?: string; saved_at: number } | { kind: 'generation'; key: string; body: GenerationBody; saved_at: number }
export const isMaterialEntry = (value: Preparation | MaterialEntryHint): value is MaterialEntryHint => 'kind' in value && value.kind === 'material_entry'
export function isGenerationOperation(value: unknown): value is GenerationOperation {
  const v = value as GenerationOperation | undefined
  return !!v && v.kind === 'generation_operation' && typeof v.key === 'string' && ['running', 'succeeded', 'failed'].includes(v.status) && typeof v.deadline === 'string'
}
export function isSession(value: unknown): value is Session {
  const v = value as Session | undefined
  return !!v && typeof v.id === 'string' && !!v.quiz && Array.isArray(v.quiz.questions) && Array.isArray(v.answers)
}
export const groundingLabel = (value?: Grounding | Verification | null) => !value || value.status === 'unknown' ? '未记录核实状态' : ({ source_backed: '有来源支持', unverified: '未联网核实', material_only: '仅依据所选材料' })[value.status]
export const stageLabel = (stage?: string | null) => ({ planning: '正在规划资料获取', retrieving: '正在准备学习依据', searching: '正在搜索相关资料', extracting: '正在读取网页正文', summarizing: '正在整理待确认范围', waiting_rate_limit: '正在等待模型额度', generating: '正在生成题目与讲解', reviewing: '正在审核题目依据', ready: '学习范围已就绪', succeeded: '关卡已生成', failed: '本次操作未完成', cancelled: '已取消范围准备', expired: '学习范围已过期' })[stage || ''] || '正在处理'
export function splitTopicInput(text: string) {
  const matches = [...text.matchAll(/https?:\/\/[^\s<>"\u3000]+/gi)]
  if (!matches.length) return undefined
  if (matches.length !== 1) throw new Error('请每次提交一个网页网址')
  const match = matches[0]
  return { url: match[0].replace(/[，。；！？）)\]}]+$/, ''), instruction: (text.slice(0, match.index) + ' ' + text.slice((match.index || 0) + match[0].length)).replace(/^[\s，。；：:]+|[\s，。；：:]+$/g, '') }
}
