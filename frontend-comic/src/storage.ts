import { Action, Data, emptyData, reducer } from './domain'
export function readData(read: () => unknown): Data {
  try {
    const d = read() as Data
    if (!d || d.version !== 1 || !Array.isArray(d.sessions) || !d.wrongs || !d.draft || typeof d.welcome !== 'boolean' || typeof d.draft.text !== 'string' || ![3,5].includes(d.draft.count) || !['easy','medium'].includes(d.draft.difficulty)) return emptyData()
    if (d.sessions.some(s => !s || !s.quiz || !Array.isArray(s.quiz.questions) || !s.quiz.questions.length || !Array.isArray(s.answers) || !Number.isInteger(s.cursor) || s.cursor < 0 || s.cursor >= s.quiz.questions.length)) return emptyData()
    return d
  } catch { return emptyData() }
}
export function commitData(data: Data, action: Action, write: (next: Data) => void) {
  const next = reducer(data, action)
  if (next !== data) write(next)
  return next
}
