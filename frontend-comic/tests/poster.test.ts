import { describe,it,expect } from 'vitest'
import { wrapText, posterContent } from '../src/poster-layout'
describe('漫画海报排版',()=>{
  it('长标题与金句按实测宽度换行，超出行数省略',()=>{
    const measure=(s:string)=>s.length*10
    expect(wrapText('123456789',measure,30,2)).toEqual(['123','45…'])
    expect(wrapText('短句',measure,100,2)).toEqual(['短句'])
    expect(wrapText('',measure,100,2)).toEqual([])
  })
  it('海报使用真实题量与报告金句，不包含正确率和排名',()=>{
    const s={quiz:{title:'RAG',questions:[{},{},{}]},report:{share_quote:'基于证据回答'}} as any
    const c=posterContent(s,0)
    expect(c).toEqual({title:'「RAG」',quote:'“基于证据回答”',badge:'第 3 关 · 通关'})
    expect(JSON.stringify(c)).not.toMatch(/正确率|超过|排名/)
  })
})
