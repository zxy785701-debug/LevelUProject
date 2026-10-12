import Taro from '@tarojs/taro'
import { Quiz, Report, Session } from './domain'
export class ApiError extends Error {
  constructor(
    message: string,
    public code = 'NETWORK_ERROR',
  ) {
    super(message)
  }
}
let requestTask: ReturnType<typeof Taro.request> | undefined
async function post<T>(path: string, data: unknown): Promise<T> {
  try {
    requestTask = Taro.request({
      url: API_BASE + path,
      method: 'POST',
      data,
      timeout: 100000,
      header: { 'content-type': 'application/json' },
    })
    const response = await requestTask
    const body = response.data as { code: number | string; message: string; data: T }
    if (response.statusCode !== 200 || body.code !== 0)
      throw new ApiError(body.message || '服务暂时无法完成请求', String(body.code))
    return body.data
  } catch (e) {
    if (e instanceof ApiError) throw e
    throw new ApiError('连接暂时中断，内容和学习记录已保留，请检查后端与网络后重试。')
  }
}
export const cancelRequest = () => requestTask?.abort()
export const generateQuiz = (text: string, question_count: 3 | 5, difficulty: 'easy' | 'medium') =>
  post<Quiz>('/api/v1/quiz/generate', { text, question_count, difficulty })
export const generateReport = (s: Session) =>
  post<Report>('/api/v1/report/generate', { quiz: s.quiz, answers: s.answers, mode: s.mode })
