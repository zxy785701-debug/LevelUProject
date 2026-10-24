import { GenerationProgress } from './GenerationProgress'
import React, { useEffect, useRef, useState } from 'react'
import { View, Text, Label, CheckboxGroup, Checkbox } from '@tarojs/components'
import { Btn, Buddy, Section, Stage, Tag, Title } from './components'
import { ApiError, RequestScope, operationKey } from './api'
import { cancelPreparation, clearPendingStudy, generateConfirmed, getPendingStudy, getPreparation, operationError, pollPreparation, prepareTopic, savePendingStudy } from './grounding-api'
import { GenerationBody, MaterialEntryHint, OperationResult, Preparation, isMaterialEntry, stageLabel } from './grounding-domain'
import { SourceReader } from './MaterialFlow'
import type { Data, Session } from './domain'
import { ImageChoice } from './QuestionImages'
import type { ImageCapabilities } from './image-domain'

type Step = 'preparing' | 'confirm' | 'source' | 'generating' | 'failure'
export function useTopicFlow({ uid, active, draft, onSession, onExit, onMaterial, imageCapabilities, onImageChange }: {
  uid: string; active: boolean; draft: Data['draft']; onSession: (session: Session) => void
  onExit: () => void; onMaterial: (hint: MaterialEntryHint) => void
  imageCapabilities?: ImageCapabilities; onImageChange: (value: boolean) => void
}) {
  const [step, setStep] = useState<Step>('preparing'), [prepared, setPrepared] = useState<Preparation>()
  const [candidateIds, setCandidateIds] = useState<string[]>([])
  const [progress, setProgress] = useState<OperationResult>(), [error, setError] = useState('')
  const [pending, setPending] = useState(() => getPendingStudy(uid))
  const scope = useRef<RequestScope>(), ticket = useRef(0), working = useRef(false), alive = useRef(true), key = useRef('')
  const callbacks = useRef({ onSession, onExit, onMaterial })
  callbacks.current = { onSession, onExit, onMaterial }
  function save(value: NonNullable<typeof pending>) { savePendingStudy(uid, value); setPending(value) }
  function clear() { clearPendingStudy(uid); setPending(undefined) }
  function begin() { scope.current?.cancel(); scope.current = new RequestScope(); working.current = true; setError(''); return { request: scope.current, id: ++ticket.current } }
  function valid(id: number) { return alive.current && id === ticket.current }
  function confirm(value: Preparation) {
    setPrepared(value); setStep('confirm'); setError(''); key.current = ''
    setCandidateIds(value.content?.candidates[0] ? [value.content.candidates[0].id] : [])
  }
  function failed(e: unknown, id: number) {
    if (!valid(id) || e instanceof ApiError && ['REQUEST_CANCELLED', 'SESSION_CHANGED'].includes(e.code)) return
    setError((e as Error).message || '暂时无法完成，请保留输入重试'); setStep('failure')
    if (e instanceof ApiError && !['NETWORK_ERROR', 'QUERY_PENDING', 'AI_BUSY', 'INVALID_OPERATION_RESPONSE', 'INVALID_SESSION_RESPONSE'].includes(e.code)) clear()
  }
  async function prepare(text: string, restoreKey?: string, restoreId?: string) {
    if (working.current) return
    const { request, id } = begin()
    setStep('preparing'); setPrepared(undefined)
    const operation = restoreKey || operationKey()
    // Do not overwrite a generation recovery key with a different preparation.
    const previous = getPendingStudy(uid)
    if (!restoreKey && previous?.kind === 'generation') {
      working.current = false; setError('还有一项已提交的出题，请先恢复原操作。'); setStep('failure'); setPending(previous); return
    }
    try {
      save({ kind: 'preparation', key: operation, text, id: restoreId, saved_at: Date.now() })
      const initial = restoreId ? await getPreparation(restoreId, request) : await prepareTopic(text, operation, request)
      if (!valid(id)) return
      if (isMaterialEntry(initial)) { clear(); callbacks.current.onMaterial(initial); return }
      setPrepared(initial)
      save({ kind: 'preparation', key: operation, text, id: initial.id, saved_at: Date.now() })
      const result = initial.status === 'running' ? await pollPreparation(initial.id, request, value => { if (valid(id)) setPrepared(value) }) : initial
      if (!valid(id)) return
      if (result.status !== 'ready') throw new ApiError(operationError(result.error_code || (result.status === 'expired' ? 'PREPARATION_EXPIRED' : 'OPERATION_CANCELLED')), result.error_code || 'OPERATION_FAILED')
      confirm(result)
    } catch (e) { failed(e, id) }
    finally { if (valid(id)) working.current = false }
  }
  async function generate(body?: GenerationBody, existingKey?: string) {
    if (working.current || !body && (!prepared || !candidateIds.length)) return
    const selection = body || { preparation_id: prepared!.id, scope_version: prepared!.version, candidate_ids: prepared!.content!.candidates.filter(c => candidateIds.includes(c.id)).map(c => c.id), question_count: draft.count, difficulty: draft.difficulty, generate_images: draft.generate_images === true }
    const { request, id } = begin()
    const operation = existingKey || key.current || (key.current = operationKey())
    setStep('generating'); setProgress(undefined)
    try {
      save({ kind: 'generation', key: operation, body: selection, saved_at: Date.now() })
      const session = await generateConfirmed(selection, operation, request, value => { if (valid(id)) setProgress(value) })
      if (!valid(id)) return
      clear(); key.current = ''; callbacks.current.onSession(session)
    } catch (e) { failed(e, id); if (valid(id) && e instanceof ApiError && !['NETWORK_ERROR', 'QUERY_PENDING', 'AI_BUSY', 'INVALID_OPERATION_RESPONSE', 'INVALID_SESSION_RESPONSE'].includes(e.code)) key.current = '' }
    finally { if (valid(id)) working.current = false }
  }
  async function restore() {
    const value = getPendingStudy(uid)
    if (!value || working.current) return
    setPending(value)
    if (value.kind === 'generation') await generate(value.body, value.key)
    else await prepare(value.text, value.key, value.id)
  }
  async function adopt(id: string) {
    const run = begin(); setStep('preparing')
    try { const value = await getPreparation(id, run.request); if (valid(run.id)) { if (value.status !== 'ready') throw new ApiError(operationError(value.error_code), value.error_code || 'PREPARATION_EXPIRED'); save({ kind: 'preparation', id, key: 'material-' + id, text: value.input_text, saved_at: Date.now() }); confirm(value) } }
    catch (e) { failed(e, run.id) }
    finally { if (valid(run.id)) working.current = false }
  }
  function leave() { scope.current?.cancel(); ticket.current++; working.current = false; callbacks.current.onExit() }
  async function back() {
    if (step === 'source') { setStep('confirm'); return }
    if (step === 'generating') { leave(); return }
    if (step === 'preparing') {
      scope.current?.cancel(); ticket.current++; working.current = false
      const value = getPendingStudy(uid)
      try {
        if (value?.kind === 'preparation') {
          const initial = value.id ? { id: value.id } : await prepareTopic(value.text, value.key)
          if (!('kind' in initial)) await cancelPreparation(initial.id)
          clear()
        }
        leave()
      } catch (e) { setError('取消尚未确认，请稍后恢复原准备。' + (e as Error).message); setStep('failure') }
      return
    }
    if (getPendingStudy(uid)?.kind === 'preparation') clear()
    leave()
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; scope.current?.cancel(); ticket.current++ } }, [])
  useEffect(() => {
    if (!active) { scope.current?.cancel(); ticket.current++; working.current = false; return }
    if (!working.current && getPendingStudy(uid) && step !== 'confirm' && step !== 'source') void restore()
  }, [active])


  let body: React.ReactNode, footer: React.ReactNode
  if (step === 'confirm' && prepared?.content) {
    body = <View className="topic-flow"><Tag color={prepared.grounding?.status === 'unverified' ? 'yellow' : 'green'}>{prepared.grounding?.status === 'unverified' ? '未联网核实' : '已取得参考资料'}</Tag><Title sub="开始前，确认你真正想学的内容。">这一关，学什么</Title>
      <View className="panel blue mt"><View className="small strong">你的学习目标</View><View className="body-copy mt">{prepared.input_text}</View></View>
      {prepared.grounding?.status === 'unverified' && <View className="hint-note">检索不可用或资料不足。确认后可围绕同一主题学习，题目会标注“未联网核实”。</View>}
      <Section>选择学习主题（可多选）</Section><View className="small muted">已选 {candidateIds.length} 个主题，知识点会自动整理。</View>
      <CheckboxGroup onChange={e => { setCandidateIds(e.detail.value); key.current = '' }}>
        {prepared.content.candidates.map((value, index) => <Label key={value.id} className={`scope-option ${candidateIds.includes(value.id) ? 'active' : ''}`}>
          <View className="scope-card-content"><Checkbox value={value.id} checked={candidateIds.includes(value.id)} color="#336ae8" />
          <View className="scope-card-copy"><View className="strong">{value.topic} · {value.domain}</View>{index === 0 && <Text className="scope-recommended">推荐</Text>}<View className="small muted scope-description">{value.description}</View></View></View>
        </Label>)}
      </CheckboxGroup>
      {prepared.evidence.length > 0 && <Btn secondary onClick={() => setStep('source')}>预览学习资料</Btn>}<View className="small muted mt">{draft.count} 题 · {draft.difficulty === 'easy' ? '轻松入门' : '稍有挑战'}。确认后才开始出题。</View><ImageChoice checked={draft.generate_images === true} onChange={value => { key.current = ''; onImageChange(value) }} capabilities={imageCapabilities} /><Buddy>方向不对，可以回去补充领域或改写主题。</Buddy></View>
    footer = <><Btn disabled={!candidateIds.length} onClick={() => void generate()}>确认范围，生成关卡</Btn><Btn secondary onClick={() => void back()}>返回修改主题</Btn></>
  } else if (step === 'source' && prepared) {
    body = <SourceReader title="本次取得的学习资料" segments={prepared.evidence} grounding={prepared.grounding} />
    footer = <Btn secondary onClick={() => setStep('confirm')}>返回确认范围</Btn>
  } else if (step === 'preparing' || step === 'generating') {
    const current = step === 'preparing' ? prepared : progress
    body = <><Stage sticker={step === 'preparing' ? '先找资料，再选方向' : '关卡正在准备'} /><Title>{step === 'preparing' ? '把学习范围弄清楚' : '你的关卡，正在成形'}</Title><View className="panel blue mt" ariaRole="status"><View className="strong">{current ? stageLabel(current.stage) : '正在提交学习目标'}</View>{current?.retry_after_seconds ? <View className="body-copy mt">约 {current.retry_after_seconds} 秒后继续；可以离开，稍后恢复原任务。</View> : <View className="body-copy mt">{step === 'preparing' ? '完成后确认想学的主题，可以多选。' : '根据确认范围准备题目，并检查依据。'}</View>}</View><GenerationProgress key={step} stage={current?.stage} /><View className="notice">关键词或指定网址会发送给资料检索服务。进度以实际处理阶段为准。</View></>
    footer = <Btn secondary onClick={() => void back()}>{step === 'preparing' ? '取消准备，返回首页' : '返回首页，稍后恢复'}</Btn>
  } else {
    body = <><Stage who="paper" sticker="输入还在，慢慢来" /><Title sub={error}>暂时没能完成</Title><View className="hint-note" ariaRole="alert">{pending?.kind === 'generation' ? '已提交的出题保留原操作，不会因查询失败重复生成。' : '可以恢复原准备，或返回补充学习目标。'}</View></>
    footer = <><Btn onClick={() => { const saved = getPendingStudy(uid); if (saved) void restore(); else if (prepared?.status === 'ready') void generate(); else void prepare(draft.text) }}>{getPendingStudy(uid) ? '恢复原操作' : prepared?.status === 'ready' ? '重新生成' : '重新准备范围'}</Btn><Btn secondary onClick={leave}>返回首页</Btn></>
  }
  return { prepare, restore, adopt, back, leave, body, footer, id: step === 'confirm' ? 'T02' : step === 'source' ? 'T03' : step === 'failure' ? 'E06' : step === 'generating' ? 'L07' : 'T01', label: step === 'confirm' ? '确认学习范围' : step === 'generating' ? '生成关卡' : '准备学习范围' }
}
