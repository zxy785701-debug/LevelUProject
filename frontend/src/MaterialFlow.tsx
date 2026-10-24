import { GenerationProgress } from './GenerationProgress'
import React, { useEffect, useRef, useState } from 'react'
import Taro from '@tarojs/taro'
import { View, Text, Input, Switch, Radio, RadioGroup, Label } from '@tarojs/components'
import { Btn, Buddy, Icon, Section, Stage, Tag, Title } from './components'
import { operationKey, ApiError, RequestScope } from './api'
import { chooseDocument, uploadMaterial, parseLink, getJob, cancelJob, getMaterial, DocumentFile } from './features-api'
import { ImageChoice } from './QuestionImages'
import type { ImageCapabilities } from './image-domain'
import { generateConfirmed, getPendingStudy, savePendingStudy, clearPendingStudy, pollDelay } from './grounding-api'
import { OperationResult, stageLabel } from './grounding-domain'
import { GroundingNotice, sourceDate } from './GroundingNotice'
import type { Grounding, Verification } from './grounding-domain'
import { Material, MaterialJob, SourceSegment, fileProblem, pageScope, parseTime, selectedSegments, segmentLabel } from './features-domain'
import type { Data, Session } from './domain'

export function SourceReader({ title, summary, segments, grounding }: { title: string; summary?: string; segments: SourceSegment[]; grounding?: Grounding | Verification | null }) {
  return <><Tag color="blue">参考资料</Tag><Title>{title}</Title>{grounding && <GroundingNotice value={grounding} />}{summary && <><Section>内容摘要</Section><View className="body-copy">{summary}</View></>}<Section>原文与引用</Section>
    {!segments.length && <View className="hint-note">没有可展示的引用片段，请保留当前核实状态。</View>}
    {segments.map(s => <View className="source-excerpt" key={s.id}>
      <View className="row"><Tag color={s.supplement ? 'yellow' : 'blue'}>{s.supplement ? '联网补充 / ' : ''}{segmentLabel(s)}</Tag>{s.url && <Text className="text-btn" onClick={() => void Taro.setClipboardData({ data: s.url! })}>复制来源链接</Text>}</View>
      {s.title && <View className="strong mt">{s.title}</View>}
      {s.knowledge && <View className="knowledge-citation">
        <View className="strong">{s.knowledge.document_title} · v{s.knowledge.document_version}</View>
        <View>{s.knowledge.source_type.toUpperCase()} · {s.page ? `第 ${s.page} 页 · ` : ''}片段 {s.knowledge.chunk_position + 1}{s.knowledge.header_path.length ? ' · ' + s.knowledge.header_path.join(' / ') : ''}</View>
        {s.knowledge.deleted && <View>原资料已删除，以下保留当时的引用快照。</View>}
        {s.knowledge.version_changed && <View>原资料已更新，以下引用来自当时的版本。</View>}
      </View>}
      {s.url && <View className="small muted mt source-url">{s.url}</View>}
      <View className="small muted mt">获取：{sourceDate(s.retrieved_at)} · 发布：{sourceDate(s.published_at)}</View>
      <View className="small muted mt">{s.truncated ? '获取内容已截断' : s.acquisition_status === 'partial' ? '页面仅部分可读取' : s.content_kind === 'snippet' ? '仅搜索摘要' : s.content_kind === 'focused_extract' ? '仅定向片段' : s.content_kind === 'full_extract' ? '网页正文（以实际返回内容为准）' : '所选材料片段'}{s.context_truncated ? ' · 出题时仅使用其中部分内容' : ''}</View>
      <View className="body-copy mt">{s.text}</View>
    </View>)}</>
}

type Kind = 'document' | 'web' | 'video'
type Step = 'input' | 'parsing' | 'confirm' | 'source' | 'generating' | 'failure'
export function useMaterialFlow({ uid, active, draft, onSession, onExit, onScope, imageCapabilities, onImageChange }: { uid: string; active: boolean; draft: Data['draft']; onSession: (s: Session) => void; onExit: () => void; onScope?: (id: string) => void; imageCapabilities?: ImageCapabilities; onImageChange: (value: boolean) => void }) {
  const [kind, setKind] = useState<Kind>('document'), [step, setStep] = useState<Step>('input')
  const [file, setFile] = useState<DocumentFile>(), [url, setUrl] = useState(''), [pages, setPages] = useState(''), [ranged, setRanged] = useState(false), [rangeError, setRangeError] = useState('')
  const [instruction, setInstruction] = useState('')
  const supportsPages = !file || /\.pdf$/i.test(file.name)
  const [start, setStart] = useState('00:00'), [end, setEnd] = useState(''), [job, setJob] = useState<MaterialJob>(), [material, setMaterial] = useState<Material>()
  const [selected, setSelected] = useState<number[]>([]), [supplement, setSupplement] = useState(false), [error, setError] = useState(''), [failureKind, setFailureKind] = useState<'parse'|'quiz'>('parse')
  const [progress, setProgress] = useState<OperationResult>()
  const generationRequest = useRef<RequestScope>()
  const currentTicket = useRef(0), working = useRef(false), alive = useRef(true), isActive = useRef(active), requestKey = useRef(''), quizKey = useRef('')
  isActive.current = active
  const storageKey = 'levelup.material-job.'+uid
  useEffect(() => { alive.current = true; return () => { alive.current = false; currentTicket.current++; generationRequest.current?.cancel() } }, [])
  useEffect(() => { if (!active) { generationRequest.current?.cancel(); currentTicket.current++; working.current = false } }, [active])
  useEffect(() => () => { if (file?.path.startsWith('blob:')) URL.revokeObjectURL(file.path) }, [file?.path])
  async function loadMaterial(id: string, valid: () => boolean, request: RequestScope) {
    const result = await getMaterial(id, request)
    if (!alive.current || !valid()) return
    setMaterial(result); setSelected(result.points.map((_, i) => i)); setSupplement(false); setError(''); setStep('confirm')
  }
  useEffect(() => {
    if (!active || step !== 'parsing' || !job?.id) return
    let live = true
    const request = new RequestScope(), until = Date.now() + 255000
    const ticket = currentTicket.current
    const valid = () => live && ticket === currentTicket.current
    async function poll() {
      for (let attempt = 0, errors = 0; valid() && attempt < 120 && Date.now() < until; attempt++) {
      try {
        const result = await getJob(job!.id, request)
        if (!valid()) return
        errors = 0
        setJob(result)
        if (result.status === 'succeeded' && result.preparation_id) { Taro.removeStorageSync(storageKey); onScope?.(result.preparation_id); return }
        if (result.status === 'succeeded' && result.material_id) { await loadMaterial(result.material_id, valid, request); return }
        if (result.status !== 'running') { setError(result.message || '解析已结束，请重新尝试'); setFailureKind('parse'); setStep('failure'); requestKey.current = ''; return }
      } catch (e) {
        if (!valid()) return
        setError((e as Error).message)
        if (!(e instanceof ApiError) || e.code !== 'NETWORK_ERROR' || ++errors > 3) { if (e instanceof ApiError && ['NOT_FOUND', 'OPERATION_EXPIRED', 'OPERATION_INTERRUPTED'].includes(e.code)) { Taro.removeStorageSync(storageKey); requestKey.current = ''; setJob(undefined) }; setFailureKind('parse'); setStep('failure'); return }
      }
      try { await request.sleep(pollDelay(attempt)) } catch { return }
      }
      if (valid()) { setError('查询暂未结束，请恢复原材料解析。'); setFailureKind('parse'); setStep('failure') }
    }
    void poll()
    return () => { live = false; request.cancel() }
  }, [active, step, job?.id])
  function open(next: Kind, initial?: { url: string; instruction?: string | null }) {
    currentTicket.current++; setKind(next); setMaterial(undefined); setJob(undefined); setStep('input'); setError(''); requestKey.current = ''; quizKey.current = ''
    if (initial) { setUrl(initial.url); setInstruction(initial.instruction || '') }
    if (next !== 'document') setFile(undefined)
    try { const saved = Taro.getStorageSync(storageKey); if (!initial && saved?.kind === next && saved?.id) { setJob(saved); setStep('parsing') } } catch {}
  }
  async function choose() {
    try { const result = await chooseDocument(); const problem = fileProblem(result.name, result.size); if (problem) throw new Error(problem); setFile(result); if (!/\.pdf$/i.test(result.name)) setRanged(false); setRangeError(''); requestKey.current = ''; setError('') }
    catch (e) { if (!/取消|cancel/i.test((e as Error).message || (e as { errMsg?: string }).errMsg || '')) setError((e as Error).message || '文件选择失败') }
  }
  async function read() {
    if (working.current) return
    let scope: string | undefined
    if (kind === 'document') {
      if (!file) { setError('请先选择文档'); return }
      try { scope = pageScope(file.name, ranged, pages); setRangeError('') }
      catch (e) { setRangeError((e as Error).message); return }
    }
    const ticket = ++currentTicket.current
    try {
      if (kind !== 'document' && !/^https?:\/\//i.test(url.trim())) throw new Error('请填写公开 HTTP/HTTPS 链接')
      const a = kind === 'video' ? parseTime(start) : 0, b = kind === 'video' && end.trim() ? parseTime(end) : undefined
      if (b !== undefined && b <= a) throw new Error('终点必须晚于起点')
      working.current = true; setError(''); setJob(undefined); setStep('parsing')
      const key = requestKey.current || (requestKey.current = operationKey())
      const result = kind === 'document' ? await uploadMaterial(file!, scope, key) : await parseLink(kind, url.trim(), key, a, b, kind === 'web' ? instruction.trim() || undefined : undefined)
      if (!alive.current || ticket !== currentTicket.current) { if (result.status === 'running') void cancelJob(result.id).catch(() => {}); return }
      setJob(result); Taro.setStorageSync(storageKey, { ...result, kind })
    } catch (e) {
      if (ticket === currentTicket.current && alive.current) { if (!(e instanceof ApiError) || e.code !== 'NETWORK_ERROR') requestKey.current = ''; setError((e as Error).message); setFailureKind('parse'); setStep('failure') }
    } finally { if (ticket === currentTicket.current) working.current = false }
  }
  async function generate() {
    if (!material || working.current) return
    const ticket = ++currentTicket.current
    try {
      const ids = selectedSegments(material.points, selected)
      const previous = getPendingStudy(uid)
      if (previous?.kind === 'generation') { setError('已有出题任务，请回首页恢复原操作。'); setFailureKind('quiz'); setStep('failure'); return }
      working.current = true; setError(''); setStep('generating')
      setProgress(undefined); generationRequest.current?.cancel(); const request = generationRequest.current = new RequestScope()
      const key = quizKey.current || (quizKey.current = operationKey())
      const body = { material_id: material.id, point_ids: ids, supplement, question_count: draft.count, difficulty: draft.difficulty, execution: 'background' as const, generate_images: draft.generate_images === true }
      savePendingStudy(uid, { kind: 'generation', key, body, saved_at: Date.now() })
      const result = await generateConfirmed(body, key, request, value => { if (alive.current && ticket === currentTicket.current) setProgress(value) })
      if (!alive.current || !isActive.current || ticket !== currentTicket.current) return
      quizKey.current = ''; clearPendingStudy(uid); Taro.removeStorageSync(storageKey); onSession(result)
    } catch (e) { if (alive.current && ticket === currentTicket.current) { if (!(e instanceof ApiError) || !['NETWORK_ERROR', 'QUERY_PENDING', 'AI_BUSY', 'INVALID_OPERATION_RESPONSE', 'INVALID_SESSION_RESPONSE'].includes(e.code)) { quizKey.current = ''; clearPendingStudy(uid) }; setError((e as Error).message); setFailureKind('quiz'); setStep('failure') } }
    finally { if (ticket === currentTicket.current) working.current = false }
  }
  async function back() {
    if (step === 'generating' || step === 'failure' && failureKind === 'quiz' && getPendingStudy(uid)?.kind === 'generation') { generationRequest.current?.cancel(); currentTicket.current++; working.current = false; onExit(); return }
    currentTicket.current++
    if (step === 'source') { setStep('confirm'); return }
    if (step === 'parsing') { try { if (job?.id) await cancelJob(job.id); Taro.removeStorageSync(storageKey) } catch (e) { setError('取消尚未确认，请保留原解析后恢复。' + (e as Error).message); setFailureKind('parse'); setStep('failure'); return } }
    if (step === 'input') { onExit(); return }
    setStep(step === 'failure' && failureKind === 'quiz' ? 'confirm' : 'input'); setError('')
  }
  const fileCard = <View className="file-card"><Icon name={kind === 'document' ? 'file' : kind === 'video' ? 'video' : 'link'} /><View className="file-details"><View className="strong">{material?.title || file?.name || (kind === 'web' ? '公开网页' : '视频字幕')}</View><View className="small muted mt">{material ? `${material.source_type.toUpperCase()} / ${material.segments.length} 个正文分段${material.caption_kind ? ' / '+material.caption_kind : ''}` : file ? `${(file.size/1024).toFixed(1)} KB` : '只读取公开正文或可访问字幕'}</View></View></View>
  let body: React.ReactNode, footer: React.ReactNode, id = { document: 'L02', web: 'L03', video: 'L04' }[kind]
  if (step === 'input') {
    body = kind === 'document' ? <><Title sub="从一份文档开始，抓住真正想学的部分。">把笔记，变成关卡</Title><View className="upload-zone mt" onClick={() => void choose()} ariaRole="button" ariaLabel="点击选择一份文档"><Icon name="upload" /><Text className="strong">点击选择一份文档</Text><Text className="small muted">PDF / Word / TXT</Text></View>{file && <View className="mt">{fileCard}</View>}<Section>学习范围</Section>
      <RadioGroup className="document-scope" onChange={e => { setRanged(e.detail.value === 'pages' && supportsPages); setRangeError(''); requestKey.current = '' }}>
        <Label className={`document-scope-option ${!ranged ? 'active' : ''}`}>
          <Radio value="all" checked={!ranged} color="#336ae8" />
          <Text>整份文档</Text>
        </Label>
        <Label className={`document-scope-option ${ranged ? 'active' : ''} ${!supportsPages ? 'unavailable' : ''}`}>
          <Radio value="pages" checked={ranged} disabled={!supportsPages} color="#336ae8" />
          <Text>指定页码</Text>
        </Label>
      </RadioGroup>
      {ranged && <View className="document-page-range">
        <Input ariaLabel="指定页码" type="text" className={`page-range ${rangeError ? 'error' : ''}`} value={pages} placeholder="例如：1-6 或 1,3-6" placeholderStyle="color:#909bae" maxlength={100} onInput={e => { setPages(e.detail.value); setRangeError(''); requestKey.current = '' }} />
        <View className="page-range-hint">{file ? '仅解析填写的 PDF 页码，可用逗号分隔多个范围。' : '可先填写页码，再选择 PDF 文件。'}</View>
        {rangeError && <View className="field-error">{rangeError}</View>}
      </View>}
      {!supportsPages && <View className="page-range-hint">DOCX 和 TXT 没有固定页码，已选择整份文档解析。</View>}
      {error && <View className="field-error">{error}</View>}
      <Buddy>不用把整本书背下来。先从你最想弄懂的几页开始。</Buddy><View className="notice">文字版 PDF / DOCX / TXT，单份最多 20 MB。</View></> : <><Title sub={kind === 'web' ? '贴上文章链接，把收藏夹里的知识学会。' : '从内容与字幕中，提炼值得记住的知识。'}>{kind === 'web' ? '网页里，也有新关卡' : '看过的视频，学进去'}</Title><View className="field"><View className="small strong">{kind === 'web' ? '网页地址' : '视频链接'}</View><Input className="input mt" ariaLabel={kind === 'web' ? '网页地址' : '视频链接'} value={url} placeholder={kind === 'web' ? 'https://…' : '粘贴 B站 / YouTube 视频链接'} onInput={e => { setUrl(e.detail.value); requestKey.current = '' }} /></View><View className={kind === 'web' ? 'panel blue' : 'panel'}><View className="row"><Tag color="blue">{kind === 'web' ? '公开网页' : '公开字幕'}</Tag><Icon name={kind === 'web' ? 'link' : 'video'} /></View><View className="body-copy mt">读取后展示真实材料标题和摘要。</View></View>{kind === 'web' && <View className="field"><View className="small strong">学习说明（选填）</View><Input className="input mt" ariaLabel="网页学习说明" value={instruction} maxlength={6000} placeholder="例如：重点学习其中的应用案例" onInput={e => { setInstruction(e.detail.value); requestKey.current = '' }} /><View className="small muted mt">网址将发送给资料检索服务；附加说明会保留在学习范围中。</View></View>}<Section>{kind === 'web' ? '读取范围' : '学习片段'}</Section>{kind === 'web' ? <><View className="check-label"><Icon name="check" />读取正文，忽略导航和广告</View><Buddy>链接打不开时，也可以复制正文，回到首页粘贴。</Buddy></> : <><View className="date-fields"><View><Text className="small">起点</Text><Input className="input" ariaLabel="片段起点" value={start} onInput={e => { setStart(e.detail.value); requestKey.current = '' }} /></View><Text className="muted">至</Text><View><Text className="small">终点</Text><Input className="input" ariaLabel="片段终点" placeholder="留空至结束" value={end} onInput={e => { setEnd(e.detail.value); requestKey.current = '' }} /></View></View><View className="small muted mt">仅解析可访问的字幕。无字幕时可回到首页粘贴自己的视频笔记。</View></>}</>
    footer = <Btn disabled={kind === 'document' ? !file : !url.trim()} onClick={() => void read()}>{kind === 'document' ? '解析这份文档' : kind === 'web' ? '读取网页内容' : '解析视频内容'}</Btn>
  } else if (step === 'parsing' || step === 'generating') {
    id = step === 'parsing' ? 'L05' : 'L07'
    body = <><Stage sticker={step === 'parsing' ? '正在读你的笔记' : '好奇心加载中'} /><Title sub={step === 'parsing' ? '材料已保留，正在提炼主题和关键概念。' : '把学习范围变成几个好问题。'}>{step === 'parsing' ? '把知识整理一下' : '你的关卡，正在成形'}</Title><View className="steps">{[[step === 'generating' ? '确认知识来源' : '材料读取', material?.title || file?.name || url], ['提炼知识点', job?.stage === 'summarizing' || step === 'generating' ? '正在整理主题与关键概念' : '等待材料读取'], [step === 'generating' ? '生成题目与讲解' : '确认学习范围', step === 'generating' ? '检查选项、讲解与引用' : '完成后由你选择出题内容']].map(([title, sub], i) => <View className="step" key={title}><View className="step-dot">{i+1}</View><View><View className="step-title">{title}</View><View className="step-sub">{sub}</View></View></View>)}</View>{error && <View className="field-error">{error}</View>}</>
    if (step === 'generating') body = <><Stage sticker="关卡正在准备" /><Title>你的关卡，正在成形</Title><View className="panel blue mt" ariaRole="status"><View className="strong">{progress ? stageLabel(progress.stage) : '正在提交所选材料范围'}</View><View className="body-copy mt">{progress?.retry_after_seconds ? `约 ${progress.retry_after_seconds} 秒后继续。` : '根据所选材料生成题目，并审核依据。'} 可以离开，稍后恢复原任务。</View></View><GenerationProgress stage={progress?.stage} /></>
    footer = <Btn secondary onClick={back}>{step === 'parsing' ? '取消解析，返回输入' : '返回首页，稍后恢复'}</Btn>
  } else if (step === 'confirm' && material) {
    id = 'L06'; body = <><Title sub="开始前，确认一下材料和学习范围。">这一关，学这些</Title><Section>学习主题</Section><View className="panel blue"><View className="strong">{material.learning_title}</View><View className="small muted mt">{material.summary}</View></View><Section>你的材料</Section>{fileCard}<View className="source-link" onClick={() => setStep('source')}><Icon name="eye" />查看原文与引用</View><Section>本轮知识点</Section><View className="chips">{material.points.map((p, i) => <View key={p.name+i} className={selected.includes(i) ? 'active' : ''} ariaRole="checkbox" ariaChecked={selected.includes(i)} onClick={() => { setSelected(old => old.includes(i) ? old.filter(v => v !== i) : [...old, i]); quizKey.current = '' }}>{p.name}</View>)}</View><View className="setting-row mt"><Text>允许联网补充知识</Text><Switch color="#336ae8" checked={supplement} disabled={!material.search_available} onChange={e => { setSupplement(e.detail.value); quizKey.current = '' }} /></View><View className="small muted mt">{material.search_available ? '补充来源将在题目讲解中单独标明。你也可以只依据自己的材料出题。' : '联网补充暂未配置，当前仅依据自己的材料出题。'}</View><ImageChoice checked={draft.generate_images === true} onChange={value => { quizKey.current = ''; onImageChange(value) }} capabilities={imageCapabilities} /></>
    footer = <Btn disabled={!selected.length} onClick={() => void generate()}>确认范围，生成关卡</Btn>
  } else if (step === 'source' && material) { id = 'K05'; body = <SourceReader title={material.title} summary={material.summary} segments={material.segments} /> }
  else { id = failureKind === 'parse' ? 'E05' : 'E06'; body = <><Stage who="paper" sticker="材料还在，慢慢来" /><Title sub={error}>{failureKind === 'parse' ? '暂时没能读懂材料' : '暂时没能生成关卡'}</Title><View className="hint-note">输入内容已保留，可以重试或调整范围。</View></>; footer = <><Btn onClick={() => void (failureKind === 'parse' ? read() : generate())}>重新试一次</Btn><Btn secondary onClick={back}>{failureKind === 'parse' ? '返回修改材料' : '返回学习范围'}</Btn></> }
  return { open, back, body, footer, id, label: step === 'source' ? '材料详情' : step === 'confirm' ? '学习范围' : step === 'generating' ? '生成关卡' : '导入学习材料' }
}
