import { describe, it, expect } from 'vitest'
import { validateInput, toggleOption, optionState, combo, RequestGuard, STORAGE_KEY, weekStats } from '../src/learning'
import { emptyData } from '../src/domain'
const q = { id:'q', type:'multi' as const, stem:'题干', options:['A','B','C','D'].map(id=>({id,text:id})), answers:['A','C'], explanation:'讲解', knowledge_point:'概念' }
describe('漫画版交互规则', () => {
  it('与原版使用独立存储', () => expect(STORAGE_KEY).toBe('levelup.comic.local.v1'))
  it('拒绝空白与超长内容，接受后端支持的 6000 字', () => {
    expect(validateInput(' \n ')).toBeTruthy()
    expect(validateInput('学'.repeat(6001))).toBeTruthy()
    expect(validateInput('学'.repeat(6000))).toBe('')
  })
  it('多选可反选，锁定后不能改动，未知选项不能提交', () => {
    expect(toggleOption(q, [], 'A', false)).toEqual(['A'])
    expect(toggleOption(q, ['A','C'], 'A', false)).toEqual(['C'])
    expect(toggleOption(q, ['A'], 'C', true)).toEqual(['A'])
    expect(toggleOption(q, [], 'Z', false)).toEqual([])
    expect(toggleOption({...q,type:'single'}, ['A'], 'B', false)).toEqual(['B'])
  })
  it('答错时同时突出正确项，未选择项淡化，答前不泄露答案', () => {
    expect(optionState(q, [], false, 'A')).toBe('')
    expect(optionState(q, ['B'], false, 'B')).toBe('is-sel')
    expect(optionState(q, ['B'], true, 'A')).toBe('is-right')
    expect(optionState(q, ['B'], true, 'B')).toBe('is-wrong')
    expect(optionState(q, ['B'], true, 'D')).toBe('is-muted')
  })
  it('计算连续与最高连击，答错会中断', () => {
    const questions = ['1','2','3','4','5'].map(id=>({...q,id}))
    const answers = questions.map((x,i)=>({question_id:x.id,selected:i===3?['B']:['A','C'],elapsed_ms:1000}))
    expect(combo({questions},answers)).toEqual({current:1,best:3})
    expect(combo({questions},answers.slice(0,3))).toEqual({current:3,best:3})
  })
  it('取消后旧响应失效，新请求不受影响', () => {
    const guard = new RequestGuard()
    const a=guard.start(); expect(guard.current(a)).toBe(true)
    guard.cancel(); expect(guard.current(a)).toBe(false)
    const b=guard.start(); expect(guard.current(a)).toBe(false); expect(guard.current(b)).toBe(true)
  })
  it('周战绩只统计本周已完成的新学，正确率按题数计算', () => {
    const d=emptyData(), now=new Date(2026,9,12,12)
    const session=(id:string,date:string,mode:'new'|'replay'='new')=>({id,quiz:{id,title:'主题',source_text:'主题',summary:'摘要',created_at:date,difficulty:'easy' as const,questions:[{...q,id:'q'}]},mode,answers:[{question_id:'q',selected:['A','C'],elapsed_ms:1000}],cursor:0,pending_ms:0,started_at:date,completed_at:date})
    d.sessions=[session('old',new Date(2026,9,11,12).toISOString()),session('new',now.toISOString()),session('replay',now.toISOString(),'replay')]
    expect(weekStats(d,now)).toEqual({completed:1,accuracy:100})
    expect(weekStats(emptyData(),now)).toEqual({completed:0,accuracy:0})
  })
})
