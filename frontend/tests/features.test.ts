import { describe, expect, it } from 'vitest'
import { parseTime, pageScope, periodDates, reportHeading, selectedSegments, fileProblem } from '../src/features-domain'

describe('材料输入校验', () => {
  it('解析视频时间并拒绝无效片段格式', () => {
    expect(parseTime('01:02:03')).toBe(3723)
    expect(parseTime('06:30')).toBe(390)
    for (const value of ['1:70', '-1', 'x', '01:02:99']) expect(() => parseTime(value)).toThrow()
  })
  it('PDF 才能按页码解析，文件上限明确', () => {
    expect(pageScope('a.pdf', true, '1–6')).toBe('1-6')
    expect(pageScope('a.pdf', true, '1，3-6')).toBe('1,3-6')
    expect(pageScope('a.txt', false, '')).toBeUndefined()
    for (const value of ['', '0', '6-2', '1,0', '1-0']) expect(() => pageScope('a.pdf', true, value)).toThrow()
    expect(() => pageScope('a.docx', true, '1')).toThrow()
    expect(fileProblem('a.doc', 20)).toContain('DOCX')
    expect(fileProblem('a.pdf', 21*1024*1024)).toContain('20 MB')
    expect(fileProblem('a.txt', 100)).toBe('')
  })
  it('知识点选择合并真实分段而不产生重复引用', () => {
    expect(selectedSegments([{ name: '一', segment_ids: ['s1', 's2'] }, { name: '二', segment_ids: ['s2'] }], [0, 1])).toEqual(['s1', 's2'])
    expect(() => selectedSegments([], [])).toThrow()
  })
})

describe('周期报告', () => {
  it('按上海自然日选择范围，与电脑时区无关', () => {
    expect(periodDates(7, new Date('2026-01-01T16:01:00Z'))).toEqual({ start: '2025-12-27', end: '2026-01-02' })
  })
  it('没有前期记录或没有提升时不声称进步', () => {
    expect(reportHeading(null, 80)).not.toContain('更懂')
    expect(reportHeading(80, 60)).not.toContain('更懂')
    expect(reportHeading(60, 80)).toContain('更懂')
  })
})
