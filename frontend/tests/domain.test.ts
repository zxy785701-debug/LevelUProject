import { describe, it, expect } from 'vitest'
import {
  emptyData,
  reducer,
  stats,
  totals,
  wrongList,
  isCorrect,
  Session,
  Question,
  inHistoryRange,
} from '../src/domain'
const question = (id: string, type: Question['type'] = 'single'): Question => ({
  id,
  type,
  stem: '问题',
  options: ['A', 'B', 'C', 'D'].map((x) => ({ id: x, text: x })),
  answers: type === 'multi' ? ['A', 'B'] : ['A'],
  explanation: '讲解',
  knowledge_point: '知识点',
})
const session = (mode: Session['mode'] = 'new'): Session => ({
  id: 's1',
  quiz: {
    id: 'q1',
    created_at: new Date().toISOString(),
    source_text: '主题',
    title: '主题',
    difficulty: 'easy',
    summary: '概述',
    questions: [question('q1'), question('q2', 'multi'), question('q3', 'judge')],
  },
  answers: [],
  cursor: 0,
  pending_ms: 0,
  started_at: new Date().toISOString(),
  mode,
})
describe('本机学习状态', () => {
  it('所有题型先存草稿，可修改且不提前判分，序列化后仍保留', () => {
    let data = reducer(emptyData(), { type: 'START', session: session() })
    data = reducer(data, { type: 'SELECT_ANSWER', selected: ['B'] })
    data = reducer(data, { type: 'SELECT_ANSWER', selected: ['A'] })
    expect(data.answerDrafts?.s1.q1).toEqual(['A'])
    data = { ...data, sessions: [{ ...data.sessions[0], cursor: 1 }] }
    data = reducer(data, { type: 'SELECT_ANSWER', selected: ['A', 'B'] })
    data = reducer(data, { type: 'SELECT_ANSWER', selected: [] })
    expect(data.answerDrafts?.s1.q2).toEqual([])
    data = { ...data, sessions: [{ ...data.sessions[0], cursor: 2 }] }
    data = reducer(data, { type: 'SELECT_ANSWER', selected: ['B'] })
    expect(JSON.parse(JSON.stringify(data)).answerDrafts.s1).toEqual({ q1: ['A'], q2: [], q3: ['B'] })
    expect(data.sessions[0].answers).toEqual([])
    expect(stats(data.sessions[0]).xp).toBe(0)
    expect(wrongList(data)).toEqual([])
    expect(reducer(data, { type: 'CLEAR_CACHE' }).answerDrafts).toEqual({})
  })
  it('进阶奖励使用关卡快照，旧关卡与重闯不追溯奖励', () => {
    const s = session()
    s.quiz.difficulty = 'medium'
    s.answers = s.quiz.questions.map(q => ({ question_id: q.id, selected: q.answers, elapsed_ms: 1000 }))
    expect(stats(s).xp).toBe(30)
    s.quiz.reward = { xp: 15, coins: 3 }
    expect(stats(s)).toMatchObject({ xp: 45, coins: 9 })
    s.mode = 'replay'
    expect(stats(s)).toMatchObject({ xp: 0, coins: 0 })
  })
  it('历史按日历周和月筛选', () => {
    const now = new Date(2026, 9, 12, 12)
    expect(inHistoryRange(new Date(2026, 9, 11).toISOString(), 1, now)).toBe(false)
    expect(inHistoryRange(new Date(2026, 9, 12, 9).toISOString(), 1, now)).toBe(true)
    expect(inHistoryRange(new Date(2026, 8, 30).toISOString(), 2, now)).toBe(false)
    expect(inHistoryRange(new Date(2026, 9, 1).toISOString(), 2, now)).toBe(true)
  })
  it('每题提交一次，锁定答案，不重复奖励，序列化后可恢复', () => {
    let d = reducer(emptyData(), { type: 'START', session: session() })
    d = reducer(d, { type: 'TICK', ms: 1000 })
    d = reducer(d, { type: 'ANSWER', selected: ['A'] })
    expect(stats(d.sessions[0]).xp).toBe(10)
    d = JSON.parse(JSON.stringify(d))
    const before = d
    d = reducer(d, { type: 'ANSWER', selected: ['B'] })
    expect(d).toBe(before)
    expect(d.sessions[0].answers[0].elapsed_ms).toBe(1000)
    expect(d.sessions[0].cursor).toBe(0)
    d = reducer(d, { type: 'NEXT' })
    expect(d.sessions[0].cursor).toBe(1)
  })
  it('非法选项、重复选项与未作答下一题不改变状态', () => {
    const d = reducer(emptyData(), { type: 'START', session: session() })
    for (const action of [
      { type: 'NEXT' },
      { type: 'ANSWER', selected: ['Z'] },
      { type: 'ANSWER', selected: ['A', 'A'] },
      { type: 'ANSWER', selected: [] },
    ] as const)
      expect(reducer(d, action as any)).toBe(d)
  })
  it('多选按集合判分，漏选、多选判错', () => {
    const q = question('q', 'multi')
    expect(isCorrect(q, ['B', 'A'])).toBe(true)
    expect(isCorrect(q, ['A'])).toBe(false)
    expect(isCorrect(q, ['A', 'B', 'C'])).toBe(false)
  })
  it.each(['replay', 'review'] as const)('%s 不发奖励，不计入分析', (mode) => {
    const s = session(mode)
    s.answers = s.quiz.questions.map((q) => ({
      question_id: q.id,
      selected: q.answers,
      elapsed_ms: 1000,
    }))
    s.completed_at = new Date().toISOString()
    const d = reducer(emptyData(), { type: 'START', session: s })
    expect(stats(s).xp).toBe(0)
    expect(totals(d).topics).toBe(0)
  })
  it('完成后统计新学，100 XP 升级', () => {
    let d = emptyData()
    for (let i = 0; i < 4; i++) {
      const s = session()
      s.id = 's' + i
      s.answers = s.quiz.questions.map((q) => ({
        question_id: q.id,
        selected: q.answers,
        elapsed_ms: 1000,
      }))
      s.completed_at = new Date().toISOString()
      d = reducer(d, { type: 'START', session: s })
    }
    expect(totals(d)).toMatchObject({ xp: 120, coins: 24, level: 2, topics: 4, streak: 1 })
  })
  it('错题复习更新掌握状态，原答案保留', () => {
    let d = reducer(emptyData(), { type: 'START', session: session() })
    d = reducer(d, { type: 'ANSWER', selected: ['B'] })
    expect(wrongList(d)).toHaveLength(1)
    const s = session('review')
    s.id = 'review'
    s.review_keys = ['s1:q1']
    d = reducer(d, { type: 'START', session: s })
    d = reducer(d, { type: 'ANSWER', selected: ['A'] })
    expect(wrongList(d)[0].status.mastered).toBe(true)
    expect(d.sessions[0].answers[0].selected).toEqual(['B'])
    expect(totals(d).xp).toBe(0)
  })
  it('清空队列不删除历史，清空草稿不改题库', () => {
    let d = reducer(emptyData(), { type: 'START', session: session() })
    d = reducer(d, { type: 'ANSWER', selected: ['B'] })
    d = reducer(d, { type: 'CLEAR_WRONGS' })
    expect(wrongList(d)[0].status.mastered).toBe(true)
    d = reducer(d, { type: 'CLEAR_CACHE' })
    expect(d.sessions[0].answers).toHaveLength(1)
  })
})
