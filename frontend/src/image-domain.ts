export interface ImageCapabilities {
  enabled?: boolean; available: boolean; reason_code?: string | null
  remaining: number; daily_limit: number; resolution: string; disclosure?: string
}
export interface ImageGeneration { requested: number; generated: number; reason_code?: string | null }
export function imageAvailability(value?: ImageCapabilities) {
  if (!value) return '正在查询配图服务…'
  if (!value.available) return '配图服务暂未就绪，仍可正常生成文字题目。'
  if (!value.remaining) return '今日配图额度已用完，仍可正常生成文字题目。'
  return `今日可用 ${value.remaining} / ${value.daily_limit} 张 · ${value.resolution}`
}
export function imageGenerationMessage(value?: ImageGeneration | null) {
  if (!value || !value.requested) return ''
  if (value.generated === value.requested) return `本关已生成 ${value.generated} 张 AI 辅助配图。`
  const count = `本轮已生成 ${value.generated} / ${value.requested} 张配图`
  if (value.reason_code === 'IMAGE_DAILY_LIMIT') return `今日配图额度不足，${count}；其余题目仍可正常作答。`
  if (value.reason_code === 'IMAGE_TIMEOUT') return `配图等待超时，${count}；所有题目仍可正常作答。`
  return `${count}，部分配图未完成；所有题目仍可正常作答。`
}
