import React, { useEffect, useRef, useState } from 'react'
import Taro, { useDidHide, useDidShow } from '@tarojs/taro'
import {
  View,
  Text,
  Input,
  Textarea,
  Switch,
  Checkbox,
  CheckboxGroup,
  Label,
  RadioGroup,
  Picker,
} from '@tarojs/components'
import { Btn, Title, Tag, Section, Buddy, Icon, Mascot, Segments } from './components'
import { ApiError, RequestScope, operationKey } from './api'
import { isSession } from './grounding-domain'
import { GroundingNotice } from './GroundingNotice'
import { SourceReader } from './MaterialFlow'
import type { Session } from './domain'
import type { DocumentFile } from './features-api'
import type { EvidenceSegment } from './grounding-domain'
import * as service from './knowledge-api'
import {
  KnowledgeTaskWatcher,
  loadKnowledgeTasks,
  saveKnowledgeTask,
  clearKnowledgeTask,
} from './knowledge-tasks'
import {
  knowledgeFileProblem,
  knowledgeStage,
  knowledgeStatus,
  knowledgeUnavailable,
} from './knowledge-domain'
import {
  KnowledgeTitle,
  KnowledgeRow,
  KnowledgeFileCard,
  KnowledgeIcon,
  KnowledgeChoice,
  knowledgeBytes,
  knowledgeUpdated,
  KnowledgeActionButton as Button,
} from './KnowledgePresentation'
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
} from './knowledge-folders'
import type {
  KnowledgeDocument,
  KnowledgeJob,
  KnowledgeTask,
  KnowledgeCapabilities,
  KnowledgeChunk,
  KnowledgeScope,
  KnowledgeAnswer,
  KnowledgeAnswerSummary,
  KnowledgeMaterialChoice,
  KnowledgeSelection,
  KnowledgeQuizSelection,
} from './knowledge-domain'
import './knowledge.scss'
import './knowledge-prototype.scss'

type Page =
  | 'library'
  | 'folder'
  | 'folder-edit'
  | 'add'
  | 'document'
  | 'ask'
  | 'quiz'
  | 'progress'
  | 'confirm'
  | 'answer'
  | 'history'
  | 'source'
type Draft = { text: string; ids: string[]; all: boolean; supplement: boolean }
const emptyDraft = (): Draft => ({ text: '', ids: [], all: false, supplement: true })
const draftKey = (uid: string) => 'levelup.knowledge.draft.v1:' + uid
function readDraft(uid: string): Draft {
  try {
    const d = Taro.getStorageSync(draftKey(uid))
    if (
      d &&
      typeof d.text === 'string' &&
      Array.isArray(d.ids) &&
      d.ids.every((v: unknown) => typeof v === 'string')
    )
      return {
        text: d.text.slice(0, 6000),
        ids: d.ids,
        all: d.all === true,
        supplement: d.supplement !== false,
      }
  } catch {}
  return emptyDraft()
}
const unique = <T extends { id: string }>(a: T[], b: T[]) => [
  ...new Map([...a, ...b].map((v) => [v.id, v])).values(),
]

export function useKnowledgeFlow({
  uid,
  active,
  onSession,
  onExit,
}: {
  uid: string
  active: boolean
  onSession: (session: Session) => void
  onExit: () => void
}) {
  const [page, setPage] = useState<Page>('library'),
    [cap, setCap] = useState<KnowledgeCapabilities>()
  const [docs, setDocs] = useState<KnowledgeDocument[]>([]),
    [docPage, setDocPage] = useState(0),
    [docTotal, setDocTotal] = useState(0)
  const [doc, setDoc] = useState<KnowledgeDocument>(),
    [chunks, setChunks] = useState<KnowledgeChunk[]>([]),
    [chunkPage, setChunkPage] = useState(0),
    [chunkTotal, setChunkTotal] = useState(0)
  const [draft, setDraft] = useState<Draft>(() => readDraft(uid)),
    [file, setFile] = useState<DocumentFile>(),
    [url, setUrl] = useState('')
  const [materials, setMaterials] = useState<KnowledgeMaterialChoice[]>([]),
    [materialPage, setMaterialPage] = useState(0),
    [materialTotal, setMaterialTotal] = useState(0)
  const [tasks, setTasks] = useState<KnowledgeTask[]>(() => loadKnowledgeTasks(uid)),
    [task, setTask] = useState<KnowledgeTask>(),
    [job, setJob] = useState<KnowledgeJob>()
  const [upload, setUpload] = useState<number>(),
    [scope, setScope] = useState<KnowledgeScope>(),
    [candidateIds, setCandidateIds] = useState<string[]>([])
  const [count, setCount] = useState<3 | 5>(3),
    [difficulty, setDifficulty] = useState<'easy' | 'medium'>('easy')
  const [folders, setFolders] = useState(() => loadKnowledgeFolders(uid)),
    [folderId, setFolderId] = useState(UNFILED_FOLDER),
    [search, setSearch] = useState('')
  const [folderEditId, setFolderEditId] = useState<string>(),
    [folderName, setFolderName] = useState(''),
    [folderDescription, setFolderDescription] = useState('')
  const [destinationId, setDestinationId] = useState(UNFILED_FOLDER),
    [importTab, setImportTab] = useState(0),
    [settingsOpen, setSettingsOpen] = useState(false),
    [contextOpen, setContextOpen] = useState(false)
  const detailFrom = useRef<Page>('library'),
    editorFrom = useRef<Page>('library'),
    addFrom = useRef<Page>('library')
  const [answer, setAnswer] = useState<KnowledgeAnswer>(),
    [history, setHistory] = useState<KnowledgeAnswerSummary[]>([]),
    [historyPage, setHistoryPage] = useState(0),
    [historyTotal, setHistoryTotal] = useState(0)
  const [source, setSource] = useState<{
    title: string
    segments: EvidenceSegment[]
    from: 'answer' | 'confirm'
  }>()
  const [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [busy, setBusy] = useState(false)
  const alive = useRef(true),
    showing = useRef(true),
    activeRef = useRef(active),
    ticket = useRef(0),
    working = useRef(false),
    request = useRef<RequestScope>(),
    watcher = useRef<KnowledgeTaskWatcher>(),
    currentTask = useRef<KnowledgeTask>()
  const pickingFile = useRef(false)
  activeRef.current = active
  const callbacks = useRef({ onSession, onExit })
  callbacks.current = { onSession, onExit }
  const refreshTasks = () => setTasks(loadKnowledgeTasks(uid))
  const remember = (value: KnowledgeTask) => {
    saveKnowledgeTask(uid, value)
    currentTask.current = value
    setTask(value)
    refreshTasks()
  }
  const forget = (value: KnowledgeTask) => {
    clearKnowledgeTask(uid, value.key)
    refreshTasks()
  }
  const pause = () => {
    ticket.current++
    request.current?.cancel()
    watcher.current?.pause()
    working.current = false
    setBusy(false)
  }
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      ticket.current++
      request.current?.cancel()
      watcher.current?.pause()
    }
  }, [uid])
  useEffect(() => {
    if (!active) pause()
    else {
      setFolders(loadKnowledgeFolders(uid))
      void refreshLibrary()
    }
  }, [active])
  useEffect(() => {
    Taro.setStorageSync(draftKey(uid), draft)
  }, [draft, uid])
  useEffect(
    () => () => {
      if (file?.path.startsWith('blob:')) URL.revokeObjectURL(file.path)
    },
    [file?.path],
  )
  function hide() {
    showing.current = false
    if (pickingFile.current) {
      watcher.current?.pause()
      return
    }
    pause()
  }
  function show() {
    showing.current = true
    if (activeRef.current && currentTask.current && page === 'progress')
      void resume(currentTask.current)
  }
  useDidHide(hide)
  useDidShow(show)
  useEffect(() => {
    if (process.env.TARO_ENV !== 'h5') return
    const visibility = () => (document.hidden ? hide() : show())
    document.addEventListener('visibilitychange', visibility)
    return () => document.removeEventListener('visibilitychange', visibility)
  }, [page])
  async function run(work: (r: RequestScope, valid: () => boolean) => Promise<void>) {
    if (working.current || !activeRef.current || !alive.current) return
    working.current = true
    setBusy(true)
    setError('')
    const version = ++ticket.current,
      r = (request.current = new RequestScope())
    const valid = () =>
      alive.current &&
      activeRef.current &&
      (showing.current || pickingFile.current) &&
      version === ticket.current
    try {
      await work(r, valid)
    } catch (e) {
      if (
        valid() &&
        !(
          e instanceof ApiError &&
          ['REQUEST_CANCELLED', 'SESSION_CHANGED', 'FILE_SELECTION_CANCELLED'].includes(e.code)
        )
      )
        setError((e as Error).message || '本次操作暂未完成，请重试。')
    } finally {
      if (version === ticket.current) {
        working.current = false
        if (alive.current) setBusy(false)
      }
    }
  }
  function navigate(next: Page) {
    pause()
    setError('')
    setNotice('')
    setPage(next)
  }
  async function refreshLibrary(more = false) {
    await run(async (r, valid) => {
      const capabilities = await service.knowledgeCapabilities(r)
      if (!valid()) return
      setCap(capabilities)
      if (!capabilities.enabled) return
      const values = await service.listKnowledgeDocuments(more ? docPage + 1 : 1, r)
      if (valid()) {
        setDocs(more ? unique(docs, values.items) : values.items)
        setDocPage(values.page)
        setDocTotal(values.total)
        refreshTasks()
      }
    })
  }
  function back() {
    if (page === 'library') {
      pause()
      callbacks.current.onExit()
      return
    }
    if (page === 'source' && source) {
      navigate(source.from)
      return
    }
    if (page === 'folder-edit') {
      navigate(editorFrom.current)
      return
    }
    if (page === 'document') {
      navigate(detailFrom.current)
      return
    }
    if (page === 'add') {
      navigate(addFrom.current)
      return
    }
    navigate('library')
    void refreshLibrary()
  }
  async function openDocument(id: string, more = false) {
    if (!more) {
      detailFrom.current = page === 'folder' ? 'folder' : 'library'
      setContextOpen(false)
      setDoc(undefined)
      setChunks([])
      navigate('document')
    }
    await run(async (r, valid) => {
      const value = await service.getKnowledgeDocument(id, r)
      const parts = value.active_revision_id
        ? await service.getKnowledgeChunks(id, more ? chunkPage + 1 : 1, r)
        : { items: [], total: 0, page: 0 }
      if (valid()) {
        setDoc(value)
        setChunks(more ? unique(chunks, parts.items) : parts.items)
        setChunkPage(parts.page)
        setChunkTotal(parts.total)
        try {
          setFolders(markKnowledgeDocumentUsed(uid, id))
        } catch {}
      }
    })
  }
  async function showHistory(more = false) {
    if (!more) navigate('history')
    await run(async (r, valid) => {
      const values = await service.listKnowledgeAnswers(more ? historyPage + 1 : 1, r)
      if (valid()) {
        setHistory(more ? unique(history, values.items) : values.items)
        setHistoryPage(values.page)
        setHistoryTotal(values.total)
      }
    })
  }
  async function showAnswer(id: string) {
    navigate('answer')
    setAnswer(undefined)
    await run(async (r, valid) => {
      const value = await service.getKnowledgeAnswer(id, r)
      if (valid()) setAnswer(value)
    })
  }
  async function finish(
    value: KnowledgeJob,
    original: KnowledgeTask,
    r: RequestScope,
    valid: () => boolean,
  ) {
    if (!valid()) return
    if (value.status !== 'succeeded') {
      setError(value.message || '本次处理未完成，可以恢复原任务或修改后重新提交。')
      return
    }
    const result = value.result as
      | {
          question_id?: string
          scope_id?: string
          document_id?: string
          status?: string
          message?: string
        }
      | undefined
    if (value.job_type === 'question' && result?.question_id) {
      const item = await service.getKnowledgeAnswer(result.question_id, r)
      if (valid()) {
        forget(original)
        setAnswer(item)
        setPage('answer')
      }
    } else if (value.job_type === 'prepare' && result?.scope_id) {
      const item = await service.getKnowledgeScope(result.scope_id, r)
      if (valid()) {
        setScope(item)
        setCandidateIds(item.recommended_candidate_ids)
        setPage('confirm')
      }
    } else if (value.job_type === 'quiz' && isSession(value.result)) {
      if (valid()) {
        forget(original)
        loadKnowledgeTasks(uid)
          .filter((v) => v.job_type === 'prepare' && v.key === original.input?.preparation_key)
          .forEach(forget)
        callbacks.current.onSession(value.result)
      }
    } else if (value.job_type === 'import' || value.job_type === 'reindex') {
      const values = await service.listKnowledgeDocuments(1, r)
      if (valid()) {
        let message = '资料已就绪，可以提问或准备关卡。'
        if (
          value.job_type === 'import' &&
          result?.document_id &&
          typeof original.input?.folder_id === 'string'
        ) {
          try {
            setFolders(placeKnowledgeDocument(uid, result.document_id, original.input.folder_id))
          } catch {
            message += ' 原存放文件夹不可用，资料已保留在未分类资料中。'
          }
        }
        forget(original)
        setDocs(values.items)
        setDocTotal(values.total)
        setDocPage(1)
        setFile(undefined)
        setNotice(message)
        setPage('library')
      }
    } else {
      forget(original)
      setError(result?.message || '当前资料不足以生成可靠结果，请补充资料或缩小目标。')
    }
  }
  async function watch(
    value: KnowledgeJob,
    original: KnowledgeTask,
    r: RequestScope,
    valid: () => boolean,
  ) {
    const saved = {
      ...original,
      id: value.id,
      progress: Math.max(original.progress, value.progress),
    }
    remember(saved)
    setJob(value)
    setUpload(undefined)
    setPage('progress')
    watcher.current?.pause()
    watcher.current = new KnowledgeTaskWatcher(uid, (next) => {
      if (valid()) {
        setJob(next)
        refreshTasks()
      }
    })
    const end = await watcher.current.watch(saved)
    if (end && valid()) await finish(end, saved, r, valid)
  }
  function selection(): KnowledgeSelection {
    return draft.all
      ? { all_ready: true, supplement: draft.supplement }
      : { document_ids: draft.ids, supplement: draft.supplement }
  }
  function newTask(
    type: KnowledgeTask['job_type'],
    title: string,
    input: Record<string, unknown>,
  ): KnowledgeTask {
    return {
      uid,
      key: operationKey(),
      job_type: type,
      title,
      input,
      progress: 0,
      saved_at: Date.now(),
    }
  }
  async function send(original: KnowledgeTask, r: RequestScope): Promise<KnowledgeJob> {
    const input = original.input || {}
    if (input.retry_id) return service.retryKnowledgeJob(String(input.retry_id), original.key, r)
    switch (original.job_type) {
      case 'question':
        return service.askKnowledge(
          String(input.text),
          input.selection as KnowledgeSelection,
          original.key,
          r,
        )
      case 'prepare':
        return service.prepareKnowledgeQuiz(
          String(input.text),
          input.selection as KnowledgeSelection,
          original.key,
          r,
        )
      case 'quiz':
        return service.generateKnowledgeQuiz(
          input.selection as unknown as KnowledgeQuizSelection,
          original.key,
          r,
        )
      case 'reindex':
        return service.reindexKnowledge(String(input.document_id), original.key, r)
      case 'import':
        if (input.url) return service.importKnowledgeWeb(String(input.url), original.key, r)
        if (input.material_id)
          return service.copyKnowledgeMaterial(String(input.material_id), original.key, r)
        if (!file || file.name !== input.filename)
          throw new ApiError(
            '请先刷新资料列表。如未找到原提交，请重新选择同一文件并恢复上传。',
            'FILE_REQUIRED',
          )
        return service.uploadKnowledgeDocument(file, original.key, r, (value) => setUpload(value))
    }
  }
  async function submit(original: KnowledgeTask) {
    // A confirmed scope may already have a queued quiz after a lost response.
    if (original.job_type === 'quiz' && !original.input?.retry_id) {
      const selection = original.input?.selection as KnowledgeQuizSelection
      const pending = loadKnowledgeTasks(uid).find(
        (t) =>
          t.job_type === 'quiz' &&
          (t.input?.selection as KnowledgeQuizSelection)?.scope_id === selection.scope_id,
      )
      if (pending) {
        await resume(pending)
        return
      }
    }
    await run(async (r, valid) => {
      remember(original)
      setPage('progress')
      setJob(undefined)
      setUpload(original.input?.filename ? 0 : undefined)
      const value = await send(original, r)
      if (valid()) await watch(value, original, r, valid)
    })
  }
  async function resume(original: KnowledgeTask) {
    await run(async (r, valid) => {
      remember(original)
      setPage('progress')
      setUpload(undefined)
      let value: KnowledgeJob
      if (original.id) value = await service.getKnowledgeJob(original.id, r)
      else {
        try {
          value = await service.lookupKnowledgeJob(original.job_type, original.key, r)
        } catch (e) {
          if (e instanceof ApiError && e.code === 'NOT_FOUND') value = await send(original, r)
          else throw e
        }
      }
      if (valid()) await watch(value, original, r, valid)
    })
  }
  async function removeDocument() {
    if (!doc) return
    const confirmed = await Taro.showModal({
      title: '删除这份资料？',
      content: '删除后立即停止检索，原文与索引会在后台清理；已有学习记录保留引用快照。',
    })
    if (!confirmed.confirm) return
    await run(async (r, valid) => {
      await service.deleteKnowledge(doc.id, r)
      if (valid()) {
        setDraft((d) => ({ ...d, ids: d.ids.filter((id) => id !== doc.id) }))
        setDocs((values) => values.filter((v) => v.id !== doc.id))
        setDocTotal((v) => Math.max(0, v - 1))
        setNotice('资料已删除，原文与索引正在后台清理。')
        setPage('library')
      }
    })
  }
  async function removeAnswer() {
    if (!answer) return
    const confirmed = await Taro.showModal({
      title: '删除这条问答？',
      content: '将删除问题、回答与引用记录，资料和已有学习关卡会保留。',
    })
    if (!confirmed.confirm) return
    await run(async (r, valid) => {
      await service.deleteKnowledgeAnswer(answer.id, r)
      if (valid()) {
        setHistory((values) => values.filter((v) => v.id !== answer.id))
        setHistoryTotal((v) => Math.max(0, v - 1))
        setAnswer(undefined)
        setNotice('问答已删除。')
        setPage('history')
      }
    })
  }
  async function fromQuestion() {
    if (!answer) return
    await run(async (r, valid) => {
      const value = await service.knowledgeQuizContext(answer.id, r)
      if (valid()) {
        setDraft({
          text: value.goal,
          ids: value.documents.map((v) => v.id),
          all: false,
          supplement: value.supplement,
        })
        setScope(undefined)
        setPage('quiz')
        setNotice('已带入原问题和资料，请确认后准备学习范围。')
      }
    })
  }
  async function chooseFile() {
    if (working.current) return
    pickingFile.current = true
    try {
      await run(async (_r, valid) => {
        const value = await service.chooseKnowledgeDocument()
        if (!valid()) {
          if (value.path.startsWith('blob:')) URL.revokeObjectURL(value.path)
          return
        }
        const problem = knowledgeFileProblem(value.name, value.size)
        if (problem) {
          if (value.path.startsWith('blob:')) URL.revokeObjectURL(value.path)
          throw new Error(problem)
        }
        setFile(value)
      })
    } finally {
      pickingFile.current = false
    }
  }
  async function listMaterials(more = false) {
    await run(async (r, valid) => {
      const values = await service.knowledgeMaterials(more ? materialPage + 1 : 1, r)
      if (valid()) {
        setMaterials(more ? unique(materials, values.items) : values.items)
        setMaterialPage(values.page)
        setMaterialTotal(values.total)
      }
    })
  }
  async function resumeDocumentJob(value: KnowledgeDocument) {
    await run(async (r, valid) => {
      const current = await service.getKnowledgeJob(value.job_id!, r)
      if (valid())
        await watch(
          current,
          {
            uid,
            key: 'document-' + current.id,
            id: current.id,
            job_type: current.job_type,
            title: value.title,
            saved_at: Date.now(),
            progress: current.progress,
          },
          r,
          valid,
        )
    })
  }
  function openFolder(id: string) {
    setFolderId(id)
    setDestinationId(id)
    navigate('folder')
  }
  function openAdd() {
    addFrom.current = page === 'folder' ? 'folder' : 'library'
    setDestinationId(page === 'folder' ? folderId : UNFILED_FOLDER)
    navigate('add')
  }
  function editFolder(id?: string) {
    const existing = folders.folders.find((f) => f.id === id)
    editorFrom.current = page === 'folder' ? 'folder' : 'library'
    setFolderEditId(existing?.id)
    setFolderName(existing?.name || '')
    setFolderDescription(existing?.description || '')
    navigate('folder-edit')
  }
  async function saveFolder() {
    await run(async (_r, valid) => {
      const state = saveKnowledgeFolder(uid, {
        id: folderEditId,
        name: folderName,
        description: folderDescription,
      })
      if (valid()) {
        const id = folderEditId || state.folders[state.folders.length - 1].id
        setFolders(state)
        setFolderId(id)
        setDestinationId(id)
        navigate('folder')
      }
    })
  }
  async function removeFolder() {
    if (!folderEditId) return
    const confirmation = await Taro.showModal({
      title: '删除此文件夹？',
      content: '只删除本机的文件夹分类，其中资料会保留在“未分类资料”中，不删除服务器资料。',
      confirmText: '删除',
      confirmColor: '#ce554d',
    }).catch(() => {
      setError('暂时无法打开确认窗口，请返回书架后重试。')
      return { confirm: false }
    })
    if (!confirmation.confirm) return
    await run(async (_r, valid) => {
      const state = deleteKnowledgeFolder(uid, folderEditId)
      if (valid()) {
        setFolders(state)
        setFolderId(UNFILED_FOLDER)
        setDestinationId(UNFILED_FOLDER)
        navigate('library')
      }
    })
  }
  function chooseDestination(index: number, documentId?: string) {
    try {
      const choice = folderChoices[index]
      if (alive.current && activeRef.current && choice) {
        if (documentId) setFolders(placeKnowledgeDocument(uid, documentId, choice.id))
        else setDestinationId(choice.id)
      }
    } catch (error) {
      if (error instanceof Error && alive.current && activeRef.current) setError(error.message)
    }
  }
  function startQuiz(documentIds?: string[]) {
    if (documentIds) editing({ ids: documentIds, all: false })
    setSettingsOpen(false)
    navigate('quiz')
  }
  function openReference(url: string) {
    if (process.env.TARO_ENV === 'h5') window.open(url, '_blank', 'noopener,noreferrer')
    else void Taro.setClipboardData({ data: url })
  }
  function showSource(ids: string[], from: 'answer' | 'confirm') {
    const segments =
      (from === 'answer' ? answer?.sources : scope?.evidence)?.filter((s) => ids.includes(s.id)) ||
      []
    setSource({ title: '本次实际引用', segments, from })
    navigate('source')
  }
  const available = !!cap?.available,
    ready = docs.filter((v) => v.status === 'ready' && v.active_revision_id)
  const validInput =
    available && draft.text.trim().length > 0 && (draft.all || draft.ids.length > 0)
  const editing = (change: Partial<Draft>) => {
    setDraft((d) => ({ ...d, ...change }))
    setScope(undefined)
  }
  const folder = folders.folders.find((f) => f.id === folderId)
  const folderChoices = [{ id: UNFILED_FOLDER, name: '未分类资料' }, ...folders.folders]
  const folderNameFor = (id: string) =>
    folders.folders.find((f) => f.id === id)?.name || '未分类资料'
  const found = searchKnowledgeLibrary(folders, docs, search)
  const unfiled = folderDocuments(folders, UNFILED_FOLDER, docs)
  const folderItems = folderDocuments(folders, folderId, docs)
  const recent = search.trim() ? found.documents : recentKnowledgeDocuments(folders, docs)
  const documentChoices = (
    <View className="knowledge-choices">
      <View className="knowledge-check" onClick={() => editing({ all: !draft.all, ids: [] })}>
        <Checkbox value="all" checked={draft.all} color="#4269a5" />
        <Text>全部已就绪资料（提交时固定版本）</Text>
      </View>
      {ready.map((d) => (
        <View
          className="knowledge-check"
          key={d.id}
          onClick={() =>
            editing({
              all: false,
              ids: draft.ids.includes(d.id)
                ? draft.ids.filter((id) => id !== d.id)
                : [...draft.ids, d.id],
            })
          }
        >
          <Checkbox value={d.id} checked={!draft.all && draft.ids.includes(d.id)} color="#4269a5" />
          <Text>
            {d.title} · v{d.version}
          </Text>
        </View>
      ))}
      {!ready.length && <View className="hint-note">先添加并处理好资料，再选择提问范围。</View>}
      {docs.length < docTotal && (
        <Btn secondary disabled={busy} onClick={() => void refreshLibrary(true)}>
          加载更多资料
        </Btn>
      )}
      {!draft.all && draft.ids.some((id) => !ready.some((d) => d.id === id)) && (
        <View className="notice">
          选择中含当前页未显示或状态已改变的资料。请加载并核对，服务端会重新检查范围。
        </View>
      )}
    </View>
  )
  const networkChoice = (
    <View className="knowledge-network">
      <View>
        <Text className="strong">联网补充</Text>
        <View className="small muted">
          默认开启；关闭后仅使用所选资料。
          {!cap?.web_available && '当前未配置联网服务，将尝试仅依据资料。'}
        </View>
      </View>
      <Switch
        checked={draft.supplement}
        color="#4269a5"
        onChange={(e) => editing({ supplement: e.detail.value })}
        aria-label="联网补充"
      />
    </View>
  )
  const feedback = (
    <>
      {error && (
        <View className="knowledge-error" role="alert">
          {error}
        </View>
      )}
      {notice && <View className="notice">{notice}</View>}
    </>
  )
  let body: React.ReactNode, footer: React.ReactNode
  if (page === 'library') {
    body = (
      <>
        <View className="hero-small">
          <KnowledgeTitle
            text={'给自己的知识，\n一个小书架'}
            mark="一个小书架"
            sub="整理材料，随时拿出来闯一关。"
          />
          <Mascot who="paper" />
        </View>
        {feedback}
        {cap && !available && (
          <View className="notice">{knowledgeUnavailable(cap.reason_code)}</View>
        )}
        <Input
          className="input knowledge-search"
          aria-label="搜索知识库"
          value={search}
          placeholder="搜索文件夹或材料"
          onInput={(e) => setSearch(e.detail.value)}
        />
        <Section link="新建" onClick={() => editFolder()}>
          我的文件夹
        </Section>
        {found.folders.map((f, i) => (
          <KnowledgeRow
            key={f.id}
            title={f.name}
            sub={`${folderDocuments(folders, f.id, docs).length} 份材料 / ${knowledgeUpdated(f.updatedAt)}`}
            onClick={() => openFolder(f.id)}
            end={i === 0 ? <Tag color="blue">私有</Tag> : undefined}
          />
        ))}
        {!!unfiled.length &&
          (!search.trim() ||
            found.documents.some((d) => !folders.assignments[d.id]) ||
            '未分类资料'.includes(search.trim())) && (
            <KnowledgeRow
              title="未分类资料"
              sub={`${unfiled.length} 份材料 / 仅自己可见`}
              onClick={() => openFolder(UNFILED_FOLDER)}
            />
          )}
        {!folders.folders.length && !docs.length && !search.trim() && (
          <View className="hint-note">还没有文件夹。可以新建一个主题，或先添加学习资料。</View>
        )}
        <Section link="添加资料" onClick={openAdd}>
          {search.trim() ? '匹配材料' : '最近使用'}
        </Section>
        <View className="stack">
          {recent.map((d) => (
            <KnowledgeFileCard key={d.id} document={d} onClick={() => void openDocument(d.id)} />
          ))}
        </View>
        {!recent.length && (
          <View className="small muted">
            {search.trim()
              ? '没有匹配的材料，试试其他关键词。'
              : '添加资料后，就可以在这里继续学习。'}
          </View>
        )}
        {docs.length < docTotal && (
          <Btn secondary disabled={busy} onClick={() => void refreshLibrary(true)}>
            加载更多资料
          </Btn>
        )}
        <View className="review-note small muted knowledge-library-note">
          你的私有材料只用于自己的学习。生成题目时可以关闭联网补充。文件夹分类保存在本机。
        </View>
        <View className="knowledge-utility-actions">
          <Button className="text-btn" onClick={() => void refreshLibrary()} disabled={busy}>
            刷新状态
          </Button>
          <Button className="text-btn" onClick={() => startQuiz()} disabled={busy || !available}>
            根据资料出题
          </Button>
          <Button
            className="text-btn"
            onClick={() => navigate('ask')}
            disabled={busy || !available}
          >
            向资料提问
          </Button>
          <Button className="text-btn" onClick={() => void showHistory()} disabled={busy}>
            查看问答
          </Button>
        </View>
        {!!tasks.length && (
          <>
            <Section>可恢复的任务</Section>
            <View className="small muted">离开页面会暂停查询，后台处理继续进行。</View>
            {tasks
              .slice()
              .reverse()
              .map((t) => (
                <View className="knowledge-card" key={t.key}>
                  <View className="strong">{t.title}</View>
                  <View className="knowledge-actions">
                    <Btn secondary disabled={busy} onClick={() => void resume(t)}>
                      恢复原提交
                    </Btn>
                    <Btn secondary disabled={busy} onClick={() => forget(t)}>
                      移除此提示
                    </Btn>
                  </View>
                </View>
              ))}
          </>
        )}
      </>
    )
    footer = (
      <Btn disabled={busy} onClick={() => editFolder()}>
        <KnowledgeIcon name="plus" tone="white" />
        新建知识文件夹
      </Btn>
    )
  } else if (page === 'folder') {
    body = (
      <>
        <Tag color="blue">私有文件夹</Tag>
        <KnowledgeTitle text={folder?.name || '未分类资料'} mark={folder?.name || '未分类资料'} />
        <View className="body-copy">
          {folder?.description || '把材料放进自己的知识书架，随时回来学习。'}
        </View>
        {feedback}
        <View className="row knowledge-folder-meta">
          <Text className="small muted">{folderItems.length} 份材料</Text>
          {folder && (
            <Button className="text-btn" onClick={() => editFolder(folder.id)}>
              编辑文件夹
            </Button>
          )}
        </View>
        <Section>学习材料</Section>
        <View className="stack">
          {folderItems.map((d) => (
            <KnowledgeFileCard key={d.id} document={d} onClick={() => void openDocument(d.id)} />
          ))}
        </View>
        {!folderItems.length && <Buddy who="paper">这个书架还空着，添加第一份学习材料吧。</Buddy>}
        <KnowledgeRow
          title="添加新材料"
          sub="导入文件或链接"
          icon="plus"
          onClick={openAdd}
          disabled={busy || !available}
        />
        <View className="review-note small muted mt">
          处理中的材料完成解析后，才会加入本轮出题。
        </View>
      </>
    )
    footer = (
      <Btn
        disabled={
          busy ||
          !available ||
          !folderItems.some((d) => d.active_revision_id && d.status === 'ready')
        }
        onClick={() =>
          startQuiz(
            folderItems
              .filter((d) => d.active_revision_id && d.status === 'ready')
              .map((d) => d.id),
          )
        }
      >
        选择材料，生成关卡
      </Btn>
    )
  } else if (page === 'folder-edit') {
    body = (
      <>
        <KnowledgeTitle text="整理一个新主题" mark="新主题" />
        {feedback}
        <View className="field">
          <Text className="knowledge-field-label">文件夹名称</Text>
          <Input
            className="input"
            aria-label="文件夹名称"
            value={folderName}
            maxlength={30}
            placeholder="给这个知识角落起个名字"
            onInput={(e) => setFolderName(e.detail.value)}
          />
        </View>
        <View className="field">
          <Text className="knowledge-field-label">简介</Text>
          <Textarea
            className="input knowledge-folder-description"
            aria-label="文件夹简介"
            value={folderDescription}
            maxlength={300}
            placeholder="记录这个文件夹想学什么"
            onInput={(e) => setFolderDescription(e.detail.value)}
          />
        </View>
        <Section>访问范围</Section>
        <View className="panel blue row knowledge-private-panel">
          <View>
            <View className="strong">仅自己可见</View>
            <View className="small muted">私有知识，不公开分享原材料。</View>
          </View>
          <Icon name="lock" />
        </View>
        <View className="small muted mt">
          文件夹分类仅保存在本机，其他设备不会同步；删除分类会保留资料。
        </View>
        {folderEditId && (
          <Button
            className="text-btn knowledge-danger mt"
            onClick={() => void removeFolder()}
            disabled={busy}
          >
            <KnowledgeIcon name="trash" tone="red" />
            删除此文件夹
          </Button>
        )}
      </>
    )
    footer = (
      <Btn disabled={busy || !folderName.trim()} onClick={() => void saveFolder()}>
        保存文件夹
      </Btn>
    )
  } else if (page === 'add') {
    body = (
      <>
        <KnowledgeTitle text="给书架添点新知识" mark="新知识" />
        {feedback}
        <Segments items={['上传文档', '添加链接']} value={importTab} onChange={setImportTab} />
        {importTab === 0 ? (
          <>
            <Button
              className="upload-zone knowledge-upload"
              disabled={busy}
              onClick={() => void chooseFile()}
            >
              <KnowledgeIcon name="upload" />
              <Text className="knowledge-upload-title">{file ? '重新选择文档' : '选择文档'}</Text>
              <Text className="small muted">PDF / Word（DOCX）/ Markdown / TXT</Text>
              <Text className="small muted">单份不超过 20 MB，PDF 需有可提取文字</Text>
            </Button>
            {file && (
              <View className="file-card knowledge-upload-preview">
                <View className="icon-tile">
                  <KnowledgeIcon name="file" />
                </View>
                <View className="file-details">
                  <View className="strong">{file.name}</View>
                  <View className="small muted">{knowledgeBytes(file.size)}</View>
                </View>
                <Tag color="blue">待处理</Tag>
              </View>
            )}
          </>
        ) : (
          <View className="field knowledge-link-field">
            <Text className="knowledge-field-label">材料链接</Text>
            <Input
              className="input"
              aria-label="材料链接"
              value={url}
              maxlength={2048}
              placeholder="粘贴公开网页链接"
              onInput={(e) => setUrl(e.detail.value)}
            />
            {!cap?.web_available && (
              <View className="small muted mt">联网服务未配置时，网页导入暂不可用。</View>
            )}
          </View>
        )}
        <Section>存放位置</Section>
        <Picker
          mode="selector"
          range={folderChoices.map((f) => f.name)}
          value={Math.max(
            0,
            folderChoices.findIndex((f) => f.id === destinationId),
          )}
          onChange={(e) => chooseDestination(Number(e.detail.value))}
        >
          <KnowledgeRow title={folderNameFor(destinationId)} sub="仅自己可见" />
        </Picker>
        <View className="business-notice knowledge-processing-note">
          {cap?.disclosure ||
            '文件保存在服务端，正文发送百炼向量化，检索片段发送 DeepSeek。联网补充不会自动发送原始文件或私有片段。'}
        </View>
        <Button
          className="text-btn knowledge-copy-entry"
          disabled={busy}
          onClick={() => void listMaterials()}
        >
          从已有材料添加
        </Button>
        {materialPage > 0 && !materials.length && (
          <View className="hint-note">暂无可以复制的材料。</View>
        )}
        {materials.map((m) => (
          <View className="knowledge-card" key={m.id}>
            <View className="strong">{m.title}</View>
            <Btn
              secondary
              disabled={busy || !available}
              onClick={() =>
                void submit(
                  newTask('import', '复制 ' + m.title, {
                    material_id: m.id,
                    folder_id: destinationId,
                  }),
                )
              }
            >
              复制到知识库
            </Btn>
          </View>
        ))}
        {materials.length < materialTotal && (
          <Btn secondary disabled={busy} onClick={() => void listMaterials(true)}>
            加载更多材料
          </Btn>
        )}
      </>
    )
    footer = (
      <Btn
        disabled={
          busy ||
          !available ||
          (importTab === 0 ? !file : !/^https?:\/\//i.test(url.trim()) || !cap?.web_available)
        }
        onClick={() =>
          void submit(
            newTask('import', importTab === 0 ? '导入 ' + file!.name : '保存网页', {
              ...(importTab === 0 ? { filename: file!.name } : { url: url.trim() }),
              folder_id: destinationId,
            }),
          )
        }
      >
        添加并处理材料
      </Btn>
    )
  } else if (page === 'document') {
    body = (
      <>
        {feedback}
        {doc ? (
          <>
            <Tag color={doc.status === 'ready' ? 'green' : 'blue'}>
              材料详情 / {knowledgeStatus(doc.status)}
            </Tag>
            <KnowledgeTitle
              text={doc.title.replace(/\.(pdf|docx|txt|md|markdown)$/i, '')}
              mark={doc.title.replace(/\.(pdf|docx|txt|md|markdown)$/i, '').slice(-4)}
            />
            <View className="small muted knowledge-document-meta">
              <Picker
                mode="selector"
                range={folderChoices.map((f) => f.name)}
                value={Math.max(
                  0,
                  folderChoices.findIndex((f) => f.id === folders.assignments[doc.id]),
                )}
                onChange={(e) => chooseDestination(Number(e.detail.value), doc.id)}
              >
                <Button className="text-btn knowledge-folder-link" aria-label="更改存放位置">
                  {folderNameFor(folders.assignments[doc.id])}
                </Button>
              </Picker>
              <Text>
                {' '}
                / {doc.source_type.toUpperCase()} / {doc.chunk_count} 个片段
                {doc.version ? ` / v${doc.version}` : ''}
              </Text>
            </View>
            {doc.message && <View className="notice">{doc.message}</View>}
            <Section>内容摘要</Section>
            <View className="body-copy">
              {chunks[0]?.text.slice(0, 240) || '处理完成后，才会展示可以定位的原文内容。'}
            </View>
            {chunks.length > 0 && <View className="small muted mt">原文摘录</View>}
            <Section>提取到的知识点</Section>
            <View className="tags">
              {[...new Set(chunks.flatMap((c) => c.location.header_path || []))]
                .slice(0, 12)
                .map((name, i) => (
                  <Tag key={name} color={i === 0 ? 'blue' : ''}>
                    {name}
                  </Tag>
                ))}
            </View>
            {!chunks.some((c) => c.location.header_path?.length) && (
              <View className="small muted">原文未提供可展示的标题，可展开上下文阅读。</View>
            )}
            <Section>原文引用</Section>
            {chunks[0] ? (
              <View className="takeaway knowledge-quotation">
                <View className="body-copy">{chunks[0].text.slice(0, 420)}</View>
                <View className="small muted mt">
                  原文摘录 /{' '}
                  {chunks[0].location.page
                    ? `第 ${chunks[0].location.page} 页`
                    : `片段 ${chunks[0].position + 1}`}
                  {chunks[0].location.header_path?.length
                    ? ' / ' + chunks[0].location.header_path.join(' / ')
                    : ''}
                </View>
              </View>
            ) : (
              <View className="hint-note">
                尚无可检索的原文片段。失败或取消的导入可以恢复原任务，过期后请重新添加。
              </View>
            )}
            <Button
              className="knowledge-context-toggle"
              aria-expanded={contextOpen}
              onClick={() => setContextOpen((v) => !v)}
            >
              <Text>{contextOpen ? '收起上下文' : '展开上下文'}</Text>
              <Text>{contextOpen ? '−' : '+'}</Text>
            </Button>
            {contextOpen && (
              <View className="knowledge-context">
                {chunks.map((c) => (
                  <View className="source-excerpt" key={c.id}>
                    <View className="small muted">
                      片段 {c.position + 1}
                      {c.location.page ? ` / 第 ${c.location.page} 页` : ''}
                      {c.location.header_path?.length
                        ? ' / ' + c.location.header_path.join(' / ')
                        : ''}
                    </View>
                    <View className="body-copy mt">{c.text}</View>
                  </View>
                ))}
                {chunks.length < chunkTotal && (
                  <Btn secondary disabled={busy} onClick={() => void openDocument(doc.id, true)}>
                    继续预览片段
                  </Btn>
                )}
              </View>
            )}
            {doc.source.url && (
              <Button
                className="source-link knowledge-reference"
                onClick={() => openReference(doc.source.url!)}
              >
                <KnowledgeIcon name="link" />
                {process.env.TARO_ENV === 'h5' ? '打开原始来源' : '复制原始来源链接'}
              </Button>
            )}
            <View className="knowledge-utility-actions">
              <Button
                className="text-btn knowledge-danger"
                disabled={busy}
                onClick={() => void removeDocument()}
              >
                移除此材料
              </Button>
              {doc.active_revision_id && (
                <Button
                  className="text-btn"
                  disabled={busy || !available}
                  onClick={() =>
                    void submit(newTask('reindex', '重建 ' + doc.title, { document_id: doc.id }))
                  }
                >
                  重建索引
                </Button>
              )}
              {doc.job_id && (
                <Button
                  className="text-btn"
                  disabled={busy}
                  onClick={() => void resumeDocumentJob(doc)}
                >
                  查看处理任务
                </Button>
              )}
            </View>
          </>
        ) : (
          <Title>正在读取资料</Title>
        )}
      </>
    )
    footer = (
      <Btn
        disabled={busy || !available || !doc?.active_revision_id || doc?.status !== 'ready'}
        onClick={() => doc && startQuiz([doc.id])}
      >
        用这份材料出题
      </Btn>
    )
  } else if (page === 'quiz') {
    body = (
      <>
        <KnowledgeTitle text="这次，从书架里学" mark="从书架里学" sub="选好材料，定一个小目标。" />
        {feedback}
        <Section>参与出题的材料</Section>
        <CheckboxGroup
          onChange={(e) => {
            const values = e.detail.value
            editing(
              values.includes('__all__') && !draft.all
                ? { all: true, ids: [] }
                : { all: false, ids: values.filter((v) => v !== '__all__') },
            )
          }}
        >
          {ready.map((d) => (
            <Label className="check-label knowledge-material-choice" key={d.id}>
              <KnowledgeChoice value={d.id} checked={!draft.all && draft.ids.includes(d.id)} />
              <Text>{d.title}</Text>
            </Label>
          ))}
          <Label className="check-label knowledge-material-choice knowledge-all-choice">
            <KnowledgeChoice value="__all__" checked={draft.all} />
            <Text>全部已就绪资料（提交时固定版本）</Text>
          </Label>
        </CheckboxGroup>
        {!ready.length && <View className="hint-note">先添加并处理好资料，再选择出题范围。</View>}
        {!draft.all && draft.ids.some((id) => !ready.some((d) => d.id === id)) && (
          <View className="notice">所选资料已更新或不在当前列表中，请重新核对资料范围。</View>
        )}
        {docs.length < docTotal && (
          <Btn secondary disabled={busy} onClick={() => void refreshLibrary(true)}>
            加载更多资料
          </Btn>
        )}
        <Section>知识来源规则</Section>
        <RadioGroup onChange={(e) => editing({ supplement: e.detail.value === 'network' })}>
          <Label className="check-label knowledge-material-choice">
            <KnowledgeChoice radio value="material" checked={!draft.supplement} />
            <Text>仅依据所选材料</Text>
          </Label>
          <Label className="check-label knowledge-material-choice">
            <KnowledgeChoice radio value="network" checked={draft.supplement} />
            <Text>允许联网补充，并标明额外来源</Text>
          </Label>
        </RadioGroup>
        <View className="panel mt knowledge-config">
          <Button
            className="knowledge-config-toggle"
            aria-expanded={settingsOpen}
            onClick={() => setSettingsOpen((v) => !v)}
          >
            <Text>出题设置</Text>
            <Text className="small muted">
              {count} 题 / {difficulty === 'easy' ? '入门' : '进阶'}
            </Text>
            <Text>{settingsOpen ? '−' : '+'}</Text>
          </Button>
          {settingsOpen && (
            <View className="knowledge-settings-body">
              <View className="field">
                <Text className="knowledge-field-label">本轮学习目标</Text>
                <Textarea
                  className="input knowledge-goal"
                  aria-label="本轮学习目标"
                  value={draft.text}
                  maxlength={6000}
                  placeholder="输入原始学习目标…"
                  onInput={(e) => editing({ text: e.detail.value })}
                />
              </View>
              <View className="config-row">
                <Text>题量</Text>
                <Picker
                  mode="selector"
                  range={['3 题', '5 题']}
                  value={count === 3 ? 0 : 1}
                  onChange={(e) => setCount(Number(e.detail.value) === 0 ? 3 : 5)}
                >
                  <Text>{count} 题⌄</Text>
                </Picker>
              </View>
              <View className="config-row">
                <Text>难度</Text>
                <Picker
                  mode="selector"
                  range={['入门', '进阶']}
                  value={difficulty === 'easy' ? 0 : 1}
                  onChange={(e) => setDifficulty(Number(e.detail.value) === 0 ? 'easy' : 'medium')}
                >
                  <Text>{difficulty === 'easy' ? '入门' : '进阶'}⌄</Text>
                </Picker>
              </View>
            </View>
          )}
        </View>
        <Buddy who="paper">只想检验自己这份笔记？保留“仅依据材料”就好。</Buddy>
      </>
    )
    footer = (
      <Btn
        disabled={busy || !available || (!draft.all && !draft.ids.length)}
        onClick={() => {
          if (!draft.text.trim()) {
            setSettingsOpen(true)
            setError('请在出题设置中填写本轮学习目标。')
            return
          }
          void submit(
            newTask('prepare', '准备学习范围', { text: draft.text.trim(), selection: selection() }),
          )
        }}
      >
        生成知识库关卡
      </Btn>
    )
  } else if (page === 'ask') {
    body = (
      <>
        <Tag color="blue">单轮问答</Tag>
        <Title sub="每次问题独立处理，不会自动带入历史问答。">想弄懂什么？</Title>
        {feedback}
        <Textarea
          className="knowledge-textarea"
          value={draft.text}
          maxlength={6000}
          placeholder="输入问题，并选择要参考的资料…"
          onInput={(e) => editing({ text: e.detail.value })}
        />
        <View className="small muted">{draft.text.length} / 6000</View>
        <Section>选择参考资料</Section>
        {documentChoices}
        {networkChoice}
        <View className="knowledge-disclosure">
          检索片段会发送学习模型处理；公开搜索仅使用获准的公开查询。问答不发放学习奖励。
        </View>
      </>
    )
    footer = (
      <Btn
        disabled={busy || !validInput}
        onClick={() =>
          void submit(
            newTask('question', '回答问题', { text: draft.text.trim(), selection: selection() }),
          )
        }
      >
        提交问题
      </Btn>
    )
  } else if (page === 'progress') {
    body = (
      <>
        <Tag color="yellow">
          {upload != null ? '正在上传文件' : job ? knowledgeStage(job.stage) : '正在确认提交状态'}
        </Tag>
        <Title>{task?.title || '后台处理中'}</Title>
        {feedback}
        <View
          className="knowledge-progress"
          role="progressbar"
          aria-valuenow={upload ?? job?.progress ?? 0}
        >
          <View style={{ width: `${upload ?? job?.progress ?? 0}%` }} />
        </View>
        <View className="strong center">
          {upload != null ? `文件传输 ${upload}%` : `任务进度 ${job?.progress ?? 0}%`}
        </View>
        <View className="hint-note">
          {upload != null
            ? '文件传输完成后，还需要解析、分块和建立索引。'
            : '任务完成后才会展示资料或学习结果。离开页面只暂停查询，可在知识库恢复原提交。'}
        </View>
        {!busy && task && (
          <Btn disabled={busy} onClick={() => void resume(task)}>
            恢复原提交
          </Btn>
        )}
        {job && ['failed', 'cancelled'].includes(job.status) && task && (
          <Btn
            secondary
            disabled={busy || !available}
            onClick={() =>
              void submit(newTask(job.job_type, task.title, { ...task.input, retry_id: job.id }))
            }
          >
            重试原任务
          </Btn>
        )}
        {job && ['queued', 'running'].includes(job.status) && (
          <Btn
            secondary
            onClick={() => {
              pause()
              void run(async (r, valid) => {
                const value = await service.cancelKnowledgeJob(job.id, r)
                if (valid()) {
                  setJob(value)
                  setError(value.message || '已取消处理。')
                }
              })
            }}
          >
            取消后台处理
          </Btn>
        )}
      </>
    )
    footer = (
      <Btn secondary onClick={back}>
        返回知识库
      </Btn>
    )
  } else if (page === 'confirm') {
    body = (
      <>
        <KnowledgeTitle
          text="这一关，学这些"
          mark="学这些"
          sub="开始前，确认一下材料和学习范围。"
        />
        {feedback}
        {scope && (
          <>
            <Section>学习主题 · 可多选</Section>
            <CheckboxGroup onChange={(e) => setCandidateIds(e.detail.value)}>
              {scope.content.candidates.map((c) => (
                <Label
                  className={`panel blue knowledge-prototype-topic ${candidateIds.includes(c.id) ? 'selected' : ''}`}
                  key={c.id}
                >
                  <View className="knowledge-topic-title">
                    <KnowledgeChoice value={c.id} checked={candidateIds.includes(c.id)} />
                    <Text className="strong">{c.topic}</Text>
                    {scope.recommended_candidate_ids.includes(c.id) && (
                      <Tag color="yellow">推荐</Tag>
                    )}
                  </View>
                  <View className="small muted mt">{c.description}</View>
                </Label>
              ))}
            </CheckboxGroup>
            <Section>你的材料</Section>
            <View className="stack">
              {scope.documents.map((d) => (
                <View className="file-card" key={d.id}>
                  <View className="icon-tile">
                    <KnowledgeIcon name={d.source_type === 'web' ? 'link' : 'file'} />
                  </View>
                  <View className="file-details">
                    <View className="strong">{d.title}</View>
                    <View className="small muted">
                      {d.source_type.toUpperCase()} / 版本 {d.version}
                    </View>
                  </View>
                  <Tag color="green">已就绪</Tag>
                </View>
              ))}
            </View>
            <Button
              className="source-link knowledge-reference"
              onClick={() =>
                showSource(
                  scope.evidence.map((s) => s.id),
                  'confirm',
                )
              }
            >
              <KnowledgeIcon name="eye" />
              查看原文与引用
            </Button>
            <Section>本轮知识点</Section>
            <View className="tags">
              {[
                ...new Set(
                  scope.content.candidates
                    .filter((c) => candidateIds.includes(c.id))
                    .flatMap((c) => c.focuses.flatMap((f) => f.points.map((p) => p.name))),
                ),
              ].map((name) => (
                <Tag color="blue" key={name}>
                  {name}
                </Tag>
              ))}
            </View>
            <View className="setting-row mt">
              <Text>允许联网补充知识</Text>
              <Switch
                checked={scope.supplement}
                color="#336ae8"
                onChange={(e) => {
                  editing({ supplement: e.detail.value })
                  navigate('quiz')
                  setNotice('知识来源规则已改变，请重新准备范围。')
                }}
              />
            </View>
            <View className="review-note small muted mt">
              补充来源将在题目讲解中单独标明。你也可以只依据自己的材料出题。
            </View>
            <View className="small muted mt">
              {count} 题 / {difficulty === 'easy' ? '入门' : '进阶'} · 本轮目标：{scope.goal}
            </View>
            <GroundingNotice value={scope.grounding} />
            <Button
              className="text-btn knowledge-edit-scope"
              onClick={() => {
                setSettingsOpen(true)
                navigate('quiz')
              }}
            >
              修改目标与资料
            </Button>
          </>
        )}
      </>
    )
    footer = (
      <Btn
        disabled={busy || !scope || !candidateIds.length || !available}
        onClick={() =>
          scope &&
          void submit(
            newTask('quiz', '生成学习关卡', {
              preparation_key: task?.job_type === 'prepare' ? task.key : '',
              selection: {
                scope_id: scope.id,
                scope_version: scope.version,
                candidate_ids: candidateIds,
                question_count: count,
                difficulty,
                supplement: scope.supplement,
              },
            }),
          )
        }
      >
        确认范围，生成关卡
      </Btn>
    )
  } else if (page === 'history') {
    body = (
      <>
        <Title sub="问答记录与闯关学习记录分别保存">问答历史</Title>
        {feedback}
        <Btn secondary disabled={busy} onClick={() => void showHistory()}>
          刷新问答
        </Btn>
        {!history.length && <Buddy who="paper">还没有问答记录。选择资料，写下第一个问题吧。</Buddy>}
        {history.map((a) => (
          <View className="knowledge-card" key={a.id}>
            <Tag color={a.status === 'answered' ? 'blue' : 'yellow'}>
              {a.status === 'answered' ? '已有回答' : '资料不足'}
            </Tag>
            <View className="strong mt">{a.question}</View>
            <View className="small muted">{a.answer_preview || a.message}</View>
            <Btn secondary disabled={busy} onClick={() => void showAnswer(a.id)}>
              查看问答
            </Btn>
          </View>
        ))}
        {history.length < historyTotal && (
          <Btn secondary disabled={busy} onClick={() => void showHistory(true)}>
            加载更多问答
          </Btn>
        )}
      </>
    )
  } else if (page === 'answer') {
    body = (
      <>
        <Tag color="blue">问答结果 · 不计奖励</Tag>
        <Title>{answer?.question || '正在读取问答'}</Title>
        {feedback}
        {answer && (
          <>
            <GroundingNotice value={answer.grounding} />
            {answer.status === 'insufficient' && (
              <View className="notice">
                {answer.message || '资料不足以可靠回答。请补充资料、缩小问题或调整联网权限后重试。'}
              </View>
            )}
            {!!answer.conflicts.length && (
              <View className="notice">
                来源存在不同表述，以下内容按各自依据分别说明。
                {answer.conflicts.map((c) => (
                  <View key={c.message}>{c.message}</View>
                ))}
              </View>
            )}
            {answer.paragraphs.map((p) => (
              <View className="knowledge-card" key={p.id}>
                <View className="body-copy">{p.text}</View>
                <Btn secondary onClick={() => showSource(p.source_ids, 'answer')}>
                  查看本段引用（{p.source_ids.length}）
                </Btn>
              </View>
            ))}
            {answer.documents.some((d) => d.deleted || d.version_changed) && (
              <View className="notice">
                部分原资料已删除或更新，当前展示的是当时保存的引用快照；继续出题需要重新核对范围。
              </View>
            )}
            <View className="small muted">
              联网补充：{answer.supplement ? '开启' : '关闭'} ·{' '}
              {answer.network.status === 'failed'
                ? '联网获取失败，已按实际依据处理。'
                : answer.network.status === 'disabled'
                  ? '本次仅查资料。'
                  : '来源以本次引用为准。'}
            </View>
            <Btn
              secondary
              onClick={() =>
                showSource(
                  answer.sources.map((s) => s.id),
                  'answer',
                )
              }
            >
              查看全部引用
            </Btn>
            <Btn secondary disabled={busy || !available} onClick={() => void fromQuestion()}>
              按这个问题出题
            </Btn>
            <Btn secondary disabled={busy} onClick={() => void removeAnswer()}>
              删除这条问答
            </Btn>
          </>
        )}
      </>
    )
  } else {
    body = <>{source && <SourceReader title={source.title} segments={source.segments} />}</>
  }
  const prototypeId = (
    {
      library: 'K01',
      folder: 'K02',
      'folder-edit': 'K03',
      add: 'K04',
      document: 'K05',
      quiz: 'K06',
      confirm: 'L06',
    } as Partial<Record<Page, string>>
  )[page]
  return {
    body: (
      <View
        className={`knowledge-flow${prototypeId ? ' knowledge-prototype' : ''}`}
        data-testid={'knowledge-' + page}
        data-prototype={prototypeId}
      >
        {body}
      </View>
    ),
    footer,
    back,
    label: {
      library: '知识库文件夹列表',
      folder: '文件夹详情',
      'folder-edit': '新建与编辑文件夹',
      add: '导入与处理材料',
      document: '材料详情与引用',
      ask: '知识库问答',
      quiz: '从知识库出题',
      progress: '后台任务',
      confirm: '来源与范围确认',
      answer: '问答结果',
      history: '问答历史',
      source: '引用来源',
    }[page],
    id: prototypeId || 'KB-' + page,
    locationKey:
      page === 'folder'
        ? folderId
        : page === 'document'
          ? doc?.id || ''
          : page === 'folder-edit'
            ? folderEditId || 'new'
            : page,
  }
}
