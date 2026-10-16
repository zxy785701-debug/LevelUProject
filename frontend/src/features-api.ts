import Taro from '@tarojs/taro'
import { api, ApiError, RequestScope, unwrap } from './api'
import { credentials } from './credentials'
import type { Material, MaterialJob, Analytics, KnowledgeMap, PeriodReport, ReportSection } from './features-domain'
export interface DocumentFile { name: string; path: string; size: number }
export async function chooseDocument(): Promise<DocumentFile> {
  if (process.env.TARO_ENV !== 'h5') {
    const result = await Taro.chooseMessageFile({ count: 1, type: 'file', extension: ['pdf', 'docx', 'txt'] })
    return result.tempFiles[0]
  }
  return new Promise((resolve, reject) => {
    const input = document.createElement('input')
    input.type = 'file'; input.accept = '.pdf,.docx,.txt'; input.style.display = 'none'
    document.body.appendChild(input)
    input.onchange = () => { const file = input.files?.[0]; input.remove(); if (file) resolve({ name: file.name, path: URL.createObjectURL(file), size: file.size }); else reject(new Error('已取消选择')) }
    input.oncancel = () => { input.remove(); reject(new Error('已取消选择')) }
    input.click()
  })
}
export async function uploadMaterial(file: DocumentFile, pages: string | undefined, key: string): Promise<MaterialJob> {
  const session = credentials()
  try {
    const response = await Taro.uploadFile({ url: API_BASE+'/api/v1/materials/document', filePath: file.path, fileName: file.name, name: 'file', timeout: 100000,
      ...(process.env.TARO_ENV === 'h5' ? { withCredentials: false } : {}),
      header: { Authorization: `Bearer ${session.token}`, 'Idempotency-Key': key }, formData: pages ? { pages } : {} })
    return unwrap<MaterialJob>({ statusCode: response.statusCode, data: JSON.parse(response.data) }, session)
  } catch (e) { if (e instanceof ApiError) throw e; throw new ApiError('文档上传暂时中断，文件仍已保留，可重新尝试。') }
}
export const parseLink = (kind: 'web' | 'video', url: string, key: string, start=0, end?: number, learning_instruction?: string) => api<MaterialJob>('/api/v1/materials/'+kind, 'POST', { url, start, end, ...(learning_instruction ? { learning_instruction } : {}) }, key)
export const getJob = (id: string, scope?: RequestScope) => api<MaterialJob>('/api/v1/material-jobs/'+id, 'GET', undefined, undefined, { scope, timeout: 15000 })
export const cancelJob = (id: string) => api<MaterialJob>('/api/v1/material-jobs/'+id+'/cancel', 'POST')
export const getMaterial = (id: string, scope?: RequestScope) => api<Material>('/api/v1/materials/'+id, 'GET', undefined, undefined, { scope, timeout: 15000 })
export const getAnalytics = (days='7', start?: string, end?: string) => api<Analytics>(`/api/v1/analytics?days=${days}${start ? '&start='+encodeURIComponent(start) : ''}${end ? '&end='+encodeURIComponent(end) : ''}`)
export const getKnowledgeMap = () => api<KnowledgeMap>('/api/v1/knowledge-map')
export const getPeriodReports = () => api<PeriodReport[]>('/api/v1/period-reports')
export const getPeriodReport = (id: string) => api<PeriodReport>('/api/v1/period-reports/'+id)
export const createPeriodReport = (days: string, start: string, end: string, sections: ReportSection[], key: string) => api<PeriodReport>('/api/v1/period-reports', 'POST', { days, start, end, sections }, key)
export async function exportPeriodReport(id: string) {
  const file = await api<{ filename: string; text: string }>('/api/v1/period-reports/'+id+'/export')
  if (process.env.TARO_ENV === 'h5') {
    const url = URL.createObjectURL(new Blob([file.text], { type: 'text/plain;charset=utf-8' }))
    const a = document.createElement('a'); a.href = url; a.download = file.filename; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  } else {
    const filePath = `${Taro.env.USER_DATA_PATH}/${file.filename}`
    await new Promise((resolve, reject) => Taro.getFileSystemManager().writeFile({ filePath, data: file.text, encoding: 'utf8', success: resolve, fail: reject }))
    if (typeof Taro.shareFileMessage !== 'function') throw new Error('报告文件已生成，当前微信版本不支持文件分享，请升级后重试。')
    await Taro.shareFileMessage({ filePath, fileName: file.filename })
  }
}
