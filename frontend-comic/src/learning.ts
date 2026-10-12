import { Answer, Data, Question, Quiz, inHistoryRange, isCorrect, stats } from './domain'
export const STORAGE_KEY = 'levelup.comic.local.v1'
export const validateInput = (text: string) => !text.trim() ? '先告诉阿皮，你想学点什么？' : Array.from(text.trim()).length > 6000 ? '内容最多支持 6000 字，请精简后再试。' : ''
export function toggleOption(q: Question, selected: string[], id: string, locked: boolean) {
  if (locked || !q.options.some(o => o.id === id)) return selected
  return q.type !== 'multi' ? [id] : selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id]
}
export function optionState(q: Question, selected: string[], locked: boolean, id: string) {
  if (!locked) return selected.includes(id) ? 'is-sel' : ''
  return q.answers.includes(id) ? 'is-right' : selected.includes(id) ? 'is-wrong' : 'is-muted'
}
export function combo(quiz: Pick<Quiz, 'questions'>, answers: Answer[]) {
  let current = 0, best = 0
  for (const a of answers) {
    const q = quiz.questions.find(x => x.id === a.question_id)
    current = q && isCorrect(q, a.selected) ? current + 1 : 0
    best = Math.max(best, current)
  }
  return { current, best }
}
export class RequestGuard {
  private token = 0
  start() { return ++this.token }
  cancel() { this.token++ }
  current(token: number) { return token === this.token }
}
export function weekStats(data: Data, now = new Date()) {
  const sessions = data.sessions.filter(s => s.mode === 'new' && s.completed_at && inHistoryRange(s.completed_at, 1, now))
  const totals = sessions.reduce((t,s) => { const v=stats(s); return {correct:t.correct+v.correct_count,total:t.total+v.total} },{correct:0,total:0})
  return { completed: sessions.length, accuracy: totals.total ? Math.round(totals.correct / totals.total * 100) : 0 }
}
