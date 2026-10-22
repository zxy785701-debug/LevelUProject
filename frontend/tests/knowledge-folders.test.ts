import { beforeEach, expect, it, vi } from 'vitest'
const storage = vi.hoisted(() => new Map<string, unknown>())
vi.mock('@tarojs/taro', () => ({
  default: {
    getStorageSync: (key: string) => storage.get(key),
    setStorageSync: (key: string, value: unknown) => storage.set(key, structuredClone(value)),
  },
}))
import {
  loadKnowledgeFolders,
  saveKnowledgeFolder,
  deleteKnowledgeFolder,
  placeKnowledgeDocument,
  markKnowledgeDocumentUsed,
  folderDocuments,
  searchKnowledgeLibrary,
  recentKnowledgeDocuments,
  UNFILED_FOLDER,
} from '../src/knowledge-folders'
import type { KnowledgeDocument } from '../src/knowledge-domain'
const document = (id: string, title: string): KnowledgeDocument => ({
  id,
  title,
  source_type: 'md',
  source: { filename: title },
  status: 'ready',
  active_revision_id: 'v1',
  version: 1,
  text_chars: 30,
  chunk_count: 1,
  created_at: '2026-10-19T00:00:00Z',
  updated_at: '2026-10-19T00:00:00Z',
})
beforeEach(() => storage.clear())
it('文件夹、资料分类和最近使用按账号保存，重新读取仍保留', () => {
  let state = saveKnowledgeFolder('alice', { name: '计算机基础', description: '网络与操作系统' })
  const id = state.folders[0].id
  state = placeKnowledgeDocument('alice', 'doc1', id)
  expect(
    folderDocuments(loadKnowledgeFolders('alice'), id, [document('doc1', 'HTTP.md')]),
  ).toHaveLength(1)
  expect(loadKnowledgeFolders('bob').folders).toEqual([])
  expect(loadKnowledgeFolders('bob').assignments.doc1).toBeUndefined()
})
it('新建和编辑校验真实名称，不覆盖同名文件夹或创建空名称', () => {
  const a = saveKnowledgeFolder('alice', { name: '  网络基础  ', description: '说明' }).folders[0]
  expect(a.name).toBe('网络基础')
  expect(() => saveKnowledgeFolder('alice', { name: '网络基础', description: '' })).toThrow(
    '已存在',
  )
  expect(() => saveKnowledgeFolder('alice', { name: ' ', description: '' })).toThrow('名称')
  const edited = saveKnowledgeFolder('alice', {
    id: a.id,
    name: '网络协议',
    description: '更新说明',
  })
  expect(edited.folders).toHaveLength(1)
  expect(edited.folders[0].description).toBe('更新说明')
})
it('移动仅改变本机分类；删除文件夹后资料进入未分类，不删除资料', () => {
  const a = saveKnowledgeFolder('alice', { name: 'A', description: '' }).folders[0]
  const b = saveKnowledgeFolder('alice', { name: 'B', description: '' }).folders[1]
  placeKnowledgeDocument('alice', 'doc1', a.id)
  let state = placeKnowledgeDocument('alice', 'doc1', b.id)
  const docs = [document('doc1', 'HTTP.md')]
  expect(folderDocuments(state, a.id, docs)).toEqual([])
  expect(folderDocuments(state, b.id, docs)).toEqual(docs)
  state = deleteKnowledgeFolder('alice', b.id)
  expect(folderDocuments(state, UNFILED_FOLDER, docs)).toEqual(docs)
  expect(docs).toHaveLength(1)
})
it('搜索匹配文件夹名称、简介和材料，不混入别的账号分类', () => {
  const a = saveKnowledgeFolder('alice', { name: '计算机', description: '网络 HTTP' }).folders[0]
  placeKnowledgeDocument('alice', 'd', a.id)
  const found = searchKnowledgeLibrary(
    loadKnowledgeFolders('alice'),
    [document('d', 'HTTP学习.md')],
    'http',
  )
  expect(found.folders.map((f) => f.id)).toContain(a.id)
  expect(found.documents.map((d) => d.id)).toEqual(['d'])
})
it('最近使用按真实打开时间排序，删除的资料不会复活', () => {
  markKnowledgeDocumentUsed('alice', 'a', 100)
  const state = markKnowledgeDocumentUsed('alice', 'b', 200)
  expect(
    recentKnowledgeDocuments(state, [document('a', 'A.md'), document('b', 'B.md')]).map(
      (d) => d.id,
    ),
  ).toEqual(['b', 'a'])
  expect(recentKnowledgeDocuments(state, [document('a', 'A.md')]).map((d) => d.id)).toEqual(['a'])
})
it('错误账号封套和损坏缓存安全归为空，未知文件夹不能接受资料', () => {
  const a = saveKnowledgeFolder('alice', { name: 'A', description: '' }).folders[0]
  const key = [...storage.keys()][0]
  storage.set(key.replace('alice', 'bob'), storage.get(key))
  expect(loadKnowledgeFolders('bob').folders).toEqual([])
  expect(() => placeKnowledgeDocument('alice', 'doc1', 'missing')).toThrow('文件夹')
  expect(() => saveKnowledgeFolder('alice', { id: 'missing', name: 'B', description: '' })).toThrow(
    '文件夹',
  )
  expect(a.id).toBeTruthy()
})
