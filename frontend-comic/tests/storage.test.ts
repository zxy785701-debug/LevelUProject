import { describe,it,expect,vi } from 'vitest'
import { readData, commitData } from '../src/storage'
import { emptyData } from '../src/domain'
describe('独立本机存储',()=>{
  it('空数据、损坏数据与读取失败均恢复为空状态',()=>{
    for(const x of [null,{}, {version:99}, {version:1,sessions:'bad'}, {version:1,sessions:[{}],wrongs:{},draft:{}}])
      expect(readData(()=>x)).toEqual(emptyData())
    expect(readData(()=>{throw new Error('denied')})).toEqual(emptyData())
  })
  it('恢复合法数据与输入草稿',()=>{
    const d=emptyData(); d.draft.text='HTTP'; expect(readData(()=>d)).toEqual(d)
  })
  it('保存失败不能提交内存状态，保存成功才返回新状态',()=>{
    const d=emptyData(), write=vi.fn(()=>{throw new Error('full')})
    expect(()=>commitData(d,{type:'WELCOME'},write)).toThrow('full')
    expect(d.welcome).toBe(false)
    expect(commitData(d,{type:'WELCOME'},vi.fn()).welcome).toBe(true)
  })
})
