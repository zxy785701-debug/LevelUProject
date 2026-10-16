import type { Kind } from './domain'
import type { EvidenceSegment, Verification, QuizSource, LearningScope } from './grounding-domain'
export type SourceSegment = EvidenceSegment
export interface MaterialPoint { name: string; segment_ids: string[] }
export interface Material { id: string; title: string; learning_title: string; summary: string; source_type: string; filename?: string; url?: string; segments: SourceSegment[]; points: MaterialPoint[]; search_available: boolean; caption_kind?: string }
export interface MaterialJob { id: string; status: 'running' | 'succeeded' | 'failed' | 'cancelled'; stage: string; material_id?: string; preparation_id?: string; error_code?: string; message?: string }
export interface KnowledgePoint { id: string; name: string; total: number; correct: number; accuracy: number; status: 'mastered' | 'weak' | 'explore'; attempt_ids: string[]; wrong_keys: string[] }
export interface KnowledgeMap { topics: { id: string; name: string; points: KnowledgePoint[] }[]; rule: string }
export interface Analytics { range: { start: string | null; end: string }; totals: { total: number; correct: number; accuracy: number | null; duration_ms: number; topics: number; rounds: number; learning_days: number }; trend: { date: string; total: number; correct: number; accuracy: number | null }[]; types: { type: Kind; total: number; correct: number; accuracy: number }[] }
export type ReportSection = 'overview' | 'performance' | 'advice'
export interface PeriodReport { id: string; status: string; error_code?: string; attempts: number; created_at: string; snapshot: { sections: ReportSection[]; current: Analytics; previous: Analytics; knowledge: KnowledgeMap; attempt_ids: string[]; provenance?: { attempt_id: string; quiz_id: string; title: string; verification: Verification; source?: QuizSource | null; learning_scope?: LearningScope | null }[] }; content?: { summary: string[]; findings: { point_id: string; analysis: string }[]; suggestions: { point_id: string; action: string }[] } }
export function parseTime(value: string) {
  if (!/^\d{1,3}:\d{2}(?::\d{2})?$/.test(value)) throw new Error('时间格式为 分:秒 或 时:分:秒')
  const parts = value.split(':').map(Number)
  if (parts.slice(1).some(n => n >= 60)) throw new Error('分和秒必须小于 60')
  return parts.reduce((n, part) => n*60+part, 0)
}
export function pageScope(name: string, ranged: boolean, pages: string) {
  if (!ranged) return undefined
  if (!/\.pdf$/i.test(name)) throw new Error('DOCX 和 TXT 没有固定页码，请选择全文')
  const clean = pages.replace(/–/g, '-').replace(/，/g, ',').trim()
  if (!/^\d+(?:\s*-\s*\d+)?(?:\s*,\s*\d+(?:\s*-\s*\d+)?)*$/.test(clean)) throw new Error('页码格式为 1-6 或 1,3-6')
  if (clean.split(',').some(part => {
    const [start, end = start] = part.split('-').map(Number)
    return !Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 1 || end < start
  })) throw new Error('页码从 1 开始，结束页不能小于起始页')
  return clean
}
export function fileProblem(name: string, size: number) {
  if (!/\.(pdf|docx|txt)$/i.test(name)) return '请选择文字版 PDF、DOCX 或 TXT'
  if (size <= 0 || size > 20*1024*1024) return '文件不能为空，单份不能超过 20 MB'
  return ''
}
export function selectedSegments(points: MaterialPoint[], selected: number[]) {
  const ids = [...new Set(selected.flatMap(i => points[i]?.segment_ids || []))]
  if (!ids.length) throw new Error('至少选择一个本轮知识点')
  return ids
}
export function periodDates(days: number, now = new Date()) {
  const end = new Date(now.getTime()+8*3600000).toISOString().slice(0, 10)
  const start = new Date(Date.parse(end+'T00:00:00Z')-(days-1)*86400000).toISOString().slice(0, 10)
  return { start, end }
}
export const reportHeading = (previous: number | null, current: number | null) => previous !== null && current !== null && current > previous ? '这段时间，\n又更懂一点。' : '把这段学习，\n慢慢变成自己的。'
export const segmentLabel = (segment: SourceSegment) => segment.page ? `第 ${segment.page} 页` : segment.start != null ? `${Math.floor(segment.start/60)}:${String(Math.floor(segment.start%60)).padStart(2, '0')} 起` : ({ snippet: '搜索摘要', full_extract: '网页正文', focused_extract: '定向片段', material: '材料分段' })[segment.content_kind || 'material']
