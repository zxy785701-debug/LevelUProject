export type Kind = 'single' | 'multi' | 'judge'
import type { Grounding, LearningScope, QuizSource, Verification } from './grounding-domain'
export interface Question {
  id: string
  type: Kind
  stem: string
  options: { id: string; text: string }[]
  answers: string[]
  explanation: string
  knowledge_point: string
  source_ids?: string[]
  grounding?: Grounding | null
  origin?: { quiz_id: string; question_id: string; title: string; learning_scope?: LearningScope | null } | null
}
export interface Quiz {
  id: string
  created_at: string
  source_text: string
  title: string
  summary: string
  difficulty: 'easy' | 'medium'
  reward?: { xp: number; coins: number }
  questions: Question[]
  source?: QuizSource | null
  learning_scope?: LearningScope | null
  grounding?: Grounding | null
}
export interface Answer {
  question_id: string
  selected: string[]
  elapsed_ms: number
}
export interface Stats {
  total: number
  correct_count: number
  accuracy: number
  duration_ms: number
  xp: number
  coins: number
  knowledge_points: { name: string; total: number; correct: number; accuracy: number }[]
  results: { question_id: string; is_correct: boolean }[]
}
export interface Report {
  quiz_id: string
  summary: string[]
  mastered_points: string[]
  weak_points: string[]
  suggestions: string[]
  share_quote: string
  stats: Stats
  verification?: Verification
  source?: QuizSource | null
  learning_scope?: LearningScope | null
}
export interface Session {
  id: string
  quiz: Quiz
  mode: 'new' | 'replay' | 'review'
  answers: Answer[]
  cursor: number
  pending_ms: number
  started_at: string
  completed_at?: string
  report?: Report
  review_keys?: string[]
}
export interface WrongState {
  mastered: boolean
  reviews: { at: string; correct: boolean }[]
}
export interface Data {
  version: 1
  sessions: Session[]
  activeId?: string
  wrongs: Record<string, WrongState>
  welcome: boolean
  draft: { text: string; count: 3 | 5; difficulty: 'easy' | 'medium' }
  answerDrafts?: Record<string, Record<string, string[]>>
}
export const emptyData = (): Data => ({
  version: 1,
  sessions: [],
  wrongs: {},
  welcome: false,
  draft: { text: '', count: 5, difficulty: 'easy' },
})
export function isCorrect(q: Question, selected: string[]) {
  return (
    q.answers.length === selected.length &&
    new Set(selected).size === selected.length &&
    q.answers.every((x) => selected.includes(x))
  )
}
export function stats(s: Session): Stats {
  const points: Stats['knowledge_points'] = []
  const results = s.quiz.questions.map((q) => {
    const a = s.answers.find((x) => x.question_id === q.id)
    const ok = !!a && isCorrect(q, a.selected)
    let p = points.find((x) => x.name === q.knowledge_point)
    if (!p) {
      p = { name: q.knowledge_point, total: 0, correct: 0, accuracy: 0 }
      points.push(p)
    }
    p.total++
    p.correct += +ok
    p.accuracy = Math.round((p.correct / p.total) * 100)
    return { question_id: q.id, is_correct: ok }
  })
  const correct = results.filter((x) => x.is_correct).length,
    total = s.quiz.questions.length
  return {
    total,
    correct_count: correct,
    accuracy: Math.round((correct / total) * 100),
    duration_ms: s.answers.reduce((n, a) => n + a.elapsed_ms, 0),
    xp: s.mode === 'new' ? correct * rewardRate(s.quiz).xp : 0,
    coins: s.mode === 'new' ? correct * rewardRate(s.quiz).coins : 0,
    knowledge_points: points,
    results,
  }
}
export const rewardRate = (quiz: Quiz) => quiz.reward || { xp: 10, coins: 2 }
export function wrongList(data: Data) {
  return data.sessions
    .filter((s) => s.mode === 'new')
    .flatMap((s) =>
      s.answers
        .filter(
          (a) =>
            !isCorrect(
              s.quiz.questions.find((q) => q.id === a.question_id)!,
              a.selected,
            ),
        )
        .map((a) => ({
          key: `${s.id}:${a.question_id}`,
          session: s,
          answer: a,
          question: s.quiz.questions.find((q) => q.id === a.question_id)!,
          status: data.wrongs[`${s.id}:${a.question_id}`] || { mastered: false, reviews: [] },
        })),
    )
}
export type Wrong = ReturnType<typeof wrongList>[number]
export type Action =
  | { type: 'DELETE_SESSION'; id: string }
  | { type: 'START'; session: Session }
  | { type: 'ANSWER'; selected: string[] }
  | { type: 'SELECT_ANSWER'; selected: string[] }
  | { type: 'NEXT' }
  | { type: 'TICK'; ms: number }
  | { type: 'REPORT'; id: string; report: Report }
  | { type: 'DRAFT'; draft: Data['draft'] }
  | { type: 'WELCOME' }
  | { type: 'WRONG'; key: string; mastered: boolean }
  | { type: 'CLEAR_WRONGS' }
  | { type: 'CLEAR_CACHE' }
  | { type: 'ACTIVE'; id?: string }
export function reducer(data: Data, action: Action): Data {
  if (action.type === 'DELETE_SESSION') {
    const answerDrafts = { ...data.answerDrafts }
    delete answerDrafts[action.id]
    return { ...data, sessions: data.sessions.filter(s => s.id !== action.id),
      activeId: data.activeId === action.id ? undefined : data.activeId, answerDrafts,
      wrongs: Object.fromEntries(Object.entries(data.wrongs).filter(([key]) => !key.startsWith(action.id + ':'))) }
  }
  if (action.type === 'WELCOME') return { ...data, welcome: true }
  if (action.type === 'DRAFT') return { ...data, draft: action.draft }
  if (action.type === 'START')
    return { ...data, sessions: [...data.sessions, action.session], activeId: action.session.id }
  if (action.type === 'ACTIVE') return { ...data, activeId: action.id }
  if (action.type === 'WRONG')
    return {
      ...data,
      wrongs: {
        ...data.wrongs,
        [action.key]: {
          ...data.wrongs[action.key],
          reviews: data.wrongs[action.key]?.reviews || [],
          mastered: action.mastered,
        },
      },
    }
  if (action.type === 'CLEAR_WRONGS') {
    const wrongs = { ...data.wrongs }
    wrongList(data).forEach((w) => {
      wrongs[w.key] = { mastered: true, reviews: wrongs[w.key]?.reviews || [] }
    })
    return { ...data, wrongs }
  }
  if (action.type === 'CLEAR_CACHE') return { ...data, draft: { ...data.draft, text: '' }, answerDrafts: {} }
  if (action.type === 'REPORT')
    return {
      ...data,
      sessions: data.sessions.map((s) =>
        s.id === action.id ? { ...s, report: action.report } : s,
      ),
    }
  const s = data.sessions.find((x) => x.id === data.activeId)
  if (!s || s.completed_at) return data
  const q = s.quiz.questions[s.cursor]
  if (action.type === 'SELECT_ANSWER') {
    if (s.answers.some(a => a.question_id === q.id) ||
      new Set(action.selected).size !== action.selected.length ||
      action.selected.some(value => !q.options.some(option => option.id === value)) ||
      (q.type !== 'multi' && action.selected.length > 1)) return data
    return { ...data, answerDrafts: { ...data.answerDrafts, [s.id]: { ...data.answerDrafts?.[s.id], [q.id]: action.selected } } }
  }
  let updated = s,
    wrongs = data.wrongs
  if (action.type === 'TICK' && !s.answers.some((a) => a.question_id === q.id))
    updated = { ...s, pending_ms: Math.min(86400000, s.pending_ms + action.ms) }
  if (action.type === 'ANSWER') {
    if (
      s.answers.some((a) => a.question_id === q.id) ||
      !action.selected.length ||
      new Set(action.selected).size !== action.selected.length ||
      action.selected.some((x) => !q.options.some((o) => o.id === x)) ||
      (q.type !== 'multi' && action.selected.length !== 1)
    )
      return data
    updated = {
      ...s,
      answers: [
        ...s.answers,
        { question_id: q.id, selected: action.selected, elapsed_ms: s.pending_ms },
      ],
      pending_ms: 0,
    }
    if (s.mode === 'review' && s.review_keys?.[s.cursor]) {
      const key = s.review_keys[s.cursor],
        correct = isCorrect(q, action.selected)
      wrongs = {
        ...wrongs,
        [key]: {
          mastered: correct,
          reviews: [...(wrongs[key]?.reviews || []), { at: new Date().toISOString(), correct }],
        },
      }
    }
  }
  if (action.type === 'NEXT') {
    if (!s.answers.some((a) => a.question_id === q.id)) return data
    updated =
      s.cursor + 1 === s.quiz.questions.length
        ? { ...s, completed_at: new Date().toISOString() }
        : { ...s, cursor: s.cursor + 1, pending_ms: 0 }
  }
  return { ...data, wrongs, sessions: data.sessions.map((x) => (x.id === s.id ? updated : x)) }
}
export function totals(data: Data) {
  const sessions = data.sessions.filter((s) => s.mode === 'new'),
    completed = sessions.filter((s) => s.completed_at)
  const xp = sessions.reduce((n, s) => n + stats(s).xp, 0),
    coins = xp / 5
  const dates = new Set(completed.map((s) => new Date(s.completed_at!).toLocaleDateString('en-CA')))
  let streak = 0,
    day = new Date()
  if (!dates.has(day.toLocaleDateString('en-CA'))) day.setDate(day.getDate() - 1)
  while (dates.has(day.toLocaleDateString('en-CA'))) {
    streak++
    day.setDate(day.getDate() - 1)
  }
  return { xp, coins, level: Math.floor(xp / 100) + 1, topics: completed.length, streak, completed }
}
export function inRange(date: string, range: number, now = Date.now()) {
  return range === 0 || now - new Date(date).getTime() <= range * 86400000
}
export function inHistoryRange(date: string, range: number, now = new Date()) {
  if (range === 0) return true
  const start = new Date(now.getFullYear(), now.getMonth(), range === 2 ? 1 : now.getDate())
  if (range === 1) start.setDate(start.getDate() - ((start.getDay() + 6) % 7))
  return new Date(date).getTime() >= start.getTime() && new Date(date).getTime() <= now.getTime()
}
export const duration = (ms: number) =>
  `${Math.floor(ms / 60000)
    .toString()
    .padStart(2, '0')}:${Math.floor((ms / 1000) % 60)
    .toString()
    .padStart(2, '0')}`
export const typeName = (type: Kind) =>
  ({ single: '单选题', multi: '多选题', judge: '判断题' })[type]
