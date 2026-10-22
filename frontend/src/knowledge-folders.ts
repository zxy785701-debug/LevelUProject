import Taro from '@tarojs/taro'
import type { KnowledgeDocument } from './knowledge-domain'

export const UNFILED_FOLDER = '__unfiled__'
export interface KnowledgeFolder {
  id: string
  name: string
  description: string
  createdAt: number
  updatedAt: number
}
export interface KnowledgeFolders {
  version: 1
  owner: string
  folders: KnowledgeFolder[]
  assignments: Record<string, string>
  recent: Record<string, number>
}
const key = (uid: string) => 'levelup.knowledge.folders.v1:' + uid
const empty = (uid: string): KnowledgeFolders => ({
  version: 1,
  owner: uid,
  folders: [],
  assignments: {},
  recent: {},
})
const entries = (value: unknown): [string, unknown][] =>
  value && typeof value === 'object' && !Array.isArray(value) ? Object.entries(value) : []
const sameName = (s: string) => s.normalize('NFKC').trim().toLocaleLowerCase()

export function loadKnowledgeFolders(uid: string): KnowledgeFolders {
  try {
    const raw = Taro.getStorageSync(key(uid)) as KnowledgeFolders | undefined
    if (!uid || !raw || raw.version !== 1 || raw.owner !== uid || !Array.isArray(raw.folders))
      return empty(uid)
    const ids = new Set<string>()
    const folders = raw.folders
      .filter((f) => {
        if (
          !f ||
          typeof f.id !== 'string' ||
          !f.id ||
          f.id === UNFILED_FOLDER ||
          ids.has(f.id) ||
          typeof f.name !== 'string' ||
          !f.name.trim() ||
          f.name.length > 30 ||
          typeof f.description !== 'string' ||
          !Number.isFinite(f.createdAt) ||
          !Number.isFinite(f.updatedAt)
        )
          return false
        ids.add(f.id)
        return true
      })
      .map((f) => ({ ...f, description: f.description.slice(0, 300) }))
    return {
      version: 1,
      owner: uid,
      folders,
      assignments: Object.fromEntries(
        entries(raw.assignments).filter(
          (entry): entry is [string, string] =>
            !!entry[0] && typeof entry[1] === 'string' && ids.has(entry[1]),
        ),
      ),
      recent: Object.fromEntries(
        entries(raw.recent).filter(
          (entry): entry is [string, number] =>
            !!entry[0] &&
            typeof entry[1] === 'number' &&
            Number.isFinite(entry[1]) &&
            entry[1] >= 0,
        ),
      ),
    }
  } catch {
    return empty(uid)
  }
}
function store(uid: string, state: KnowledgeFolders) {
  if (!uid || state.owner !== uid) throw new Error('账号已切换，请重新打开当前账号的文件夹。')
  try {
    Taro.setStorageSync(key(uid), state)
  } catch {
    throw new Error('无法保存本机文件夹，请检查可用空间后重试；服务器资料不会因此删除。')
  }
  return state
}
export function saveKnowledgeFolder(
  uid: string,
  input: { id?: string; name: string; description: string },
): KnowledgeFolders {
  const state = loadKnowledgeFolders(uid),
    name = input.name.trim(),
    description = input.description.trim()
  if (!name || name.length > 30) throw new Error('请输入 1–30 个字的文件夹名称。')
  if (description.length > 300) throw new Error('文件夹简介请控制在 300 个字以内。')
  if (input.id && !state.folders.some((f) => f.id === input.id))
    throw new Error('这个文件夹已不存在，请返回书架重新选择。')
  if (state.folders.some((f) => f.id !== input.id && sameName(f.name) === sameName(name)))
    throw new Error('同名文件夹已存在，请换一个名称。')
  const now = Date.now()
  const folder = input.id
    ? { ...state.folders.find((f) => f.id === input.id)!, name, description, updatedAt: now }
    : {
        id: 'kf-' + now.toString(36) + '-' + Math.random().toString(36).slice(2),
        name,
        description,
        createdAt: now,
        updatedAt: now,
      }
  return store(uid, {
    ...state,
    folders: input.id
      ? state.folders.map((f) => (f.id === input.id ? folder : f))
      : [...state.folders, folder],
  })
}
export function deleteKnowledgeFolder(uid: string, id: string): KnowledgeFolders {
  const state = loadKnowledgeFolders(uid)
  return store(uid, {
    ...state,
    folders: state.folders.filter((f) => f.id !== id),
    assignments: Object.fromEntries(
      Object.entries(state.assignments).filter(([, folder]) => folder !== id),
    ),
  })
}
export function placeKnowledgeDocument(
  uid: string,
  documentId: string,
  folderId: string,
): KnowledgeFolders {
  const state = loadKnowledgeFolders(uid)
  if (folderId !== UNFILED_FOLDER && !state.folders.some((f) => f.id === folderId))
    throw new Error('存放文件夹已不存在，请重新选择。')
  const assignments = { ...state.assignments }
  if (folderId === UNFILED_FOLDER) delete assignments[documentId]
  else assignments[documentId] = folderId
  return store(uid, { ...state, assignments })
}
export function markKnowledgeDocumentUsed(
  uid: string,
  documentId: string,
  at = Date.now(),
): KnowledgeFolders {
  const state = loadKnowledgeFolders(uid)
  const recent = Object.fromEntries(
    Object.entries({ ...state.recent, [documentId]: at })
      .sort((a, b) => b[1] - a[1])
      .slice(0, 100),
  )
  return store(uid, { ...state, recent })
}
export function folderDocuments(
  state: KnowledgeFolders,
  folderId: string,
  docs: KnowledgeDocument[],
) {
  return docs.filter(
    (d) => d.status !== 'deleted' && (state.assignments[d.id] || UNFILED_FOLDER) === folderId,
  )
}
export function searchKnowledgeLibrary(
  state: KnowledgeFolders,
  docs: KnowledgeDocument[],
  query: string,
) {
  const q = sameName(query),
    live = docs.filter((d) => d.status !== 'deleted')
  const documents = live.filter((d) => !q || sameName(d.title).includes(q))
  const matched = new Set(documents.map((d) => state.assignments[d.id]).filter(Boolean))
  return {
    folders: state.folders.filter(
      (f) => !q || sameName(f.name + ' ' + f.description).includes(q) || matched.has(f.id),
    ),
    documents,
  }
}
export function recentKnowledgeDocuments(state: KnowledgeFolders, docs: KnowledgeDocument[]) {
  return docs
    .filter((d) => d.status !== 'deleted')
    .slice()
    .sort(
      (a, b) =>
        (state.recent[b.id] || Date.parse(b.updated_at) || 0) -
        (state.recent[a.id] || Date.parse(a.updated_at) || 0),
    )
    .slice(0, 3)
}
