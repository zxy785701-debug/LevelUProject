import React, { useEffect, useRef, useState } from 'react'
import Taro, { useDidHide, useDidShow, useShareAppMessage } from '@tarojs/taro'
import { View, Text, ScrollView, Textarea, Input, Canvas, Image } from '@tarojs/components'
import { Provider, useStore } from '../../store'
import {
  Quiz,
  Question,
  Session,
  Wrong,
  stats,
  totals,
  wrongList,
  isCorrect,
  duration,
  typeName,
  inRange,
  inHistoryRange,
  rewardRate,
} from '../../domain'
import { generateQuiz, generateReport, cancelRequest, operationKey, submitAnswer, saveProgress, replayQuiz, reviewWrongs, api, getLearning, User, ApiError } from '../../api'
import { useAuth, wechatCode, PRIVACY, TERMS } from '../../auth'
import { clearCredentials } from '../../credentials'
import { Trend } from '../../Trend'
import { WeeklyReview } from '../../WeeklyReview'
import { Mine, SettingsView } from '../../account'
import { makePoster, savePoster, saveExport } from '../../platform'
import {
  Icon,
  Mascot,
  Title,
  Hero,
  Stage,
  Buddy,
  Btn,
  Tag,
  Section,
  Row,
  Stat,
  Segments,
  Chips,
  Mastery,
  Crew,
} from '../../components'

type Screen =
  | 'welcome'
  | 'home'
  | 'generating'
  | 'ready'
  | 'quiz'
  | 'result'
  | 'reportLoading'
  | 'report'
  | 'share'
  | 'review'
  | 'history'
  | 'detail'
  | 'analytics'
  | 'wrongs'
  | 'wrong'
  | 'queue'
  | 'reviewResult'
  | 'mine'
  | 'settings'
  | 'data'
  | 'question'
  | 'error'
const labels: Record<Screen, string> = {
  welcome: '欢迎来到 LevelUProject',
  home: 'LevelUProject',
  generating: '生成关卡',
  ready: '准备开始',
  quiz: '本轮闯关',
  result: '通关啦',
  reportLoading: '整理学习收获',
  report: '学习报告',
  share: '分享学习收获',
  review: '个人学习中心',
  history: '历史记录',
  detail: '学习详情',
  analytics: '学习数据',
  wrongs: '错题本',
  wrong: '错题详情',
  queue: '旧识重温',
  reviewResult: '复习完成',
  mine: '我的',
  settings: '设置',
  data: '数据与账户管理',
  question: '逐题回看',
  error: '稍等一下',
}
const baseIds: Partial<Record<Screen, string>> = {
  welcome: 'L19',
  home: 'L01',
  generating: 'L07',
  ready: 'L08',
  result: 'L15',
  reportLoading: 'L16',
  report: 'L17',
  share: 'L18',
  review: 'R01',
  history: 'R02',
  detail: 'R03',
  analytics: 'R05',
  wrongs: 'R08',
  wrong: 'R09',
  queue: 'R10',
  reviewResult: 'R12',
  mine: 'A01',
  settings: 'A03',
  data: 'E10',
  question: 'L12',
  error: 'E06',
}
const uid = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
const when = (value: string) =>
  new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
const optionText = (q: Question, selected: string[]) =>
  selected.map((x) => `${x} ${q.options.find((o) => o.id === x)?.text || ''}`).join('；')

export default function Index() {
  const auth = useAuth()
  return auth.user && !auth.loading ? <Provider key={auth.user.id}><LearningPage /></Provider> : <>{auth.loginView}</>
}
function LearningPage() {
  const { data, dispatch, upsert, refresh, loading: cloudLoading, error: cloudError } = useStore()
  const auth = useAuth()
  const profile = { ...totals(data), ...auth.user.stats },
    wrongs = wrongList(data)
  const [screen, setScreen] = useState<Screen>(() => (data.welcome ? 'home' : 'welcome'))
  const [recordId, setRecordId] = useState(data.activeId || ''),
    [wrongKey, setWrongKey] = useState(''),
    [qid, setQid] = useState('')
  const [selected, setSelected] = useState<string[]>([]),
    [expanded, setExpanded] = useState(false),
    [config, setConfig] = useState(false),
    [paused, setPaused] = useState(false)
  const [search, setSearch] = useState(''),
    [historyRange, setHistoryRange] = useState(0),
    [analyticsRange, setAnalyticsRange] = useState(0),
    [wrongTab, setWrongTab] = useState(0),
    [topicFilter, setTopicFilter] = useState(0)
  const [dialog, setDialog] = useState<{ title: string; message: string; confirm?: () => void }>(),
    [error, setError] = useState({ message: '', kind: 'quiz' as 'quiz' | 'report' })
  const [poster, setPoster] = useState(''),
    [saving, setSaving] = useState(false)
  const quizOperation = useRef<{ signature: string; key: string }>()
  const scrollPositions = useRef<Record<string, number>>({})
  const selectionDrafts = useRef<Record<string, string[]>>({})
  const answerTimes = useRef<Record<string, number>>({})
  const [questionBusy, setQuestionBusy] = useState(false)
  const reportOperations = useRef<Record<string, string>>({})
  const stack = useRef<Screen[]>([]),
    token = useRef(0),
    visible = useRef(true),
    screenRef = useRef(screen),
    busy = useRef(false)
  screenRef.current = screen
  const active = data.sessions.find((s) => s.id === data.activeId),
    record = data.sessions.find((s) => s.id === recordId) || active
  const wrong = wrongs.find((w) => w.key === wrongKey),
    current = active?.quiz.questions[active.cursor],
    answered = active?.answers.find((a) => a.question_id === current?.id)
  const sStats = record ? stats(record) : undefined,
    pending = wrongs.filter((w) => !w.status.mastered)
  const scrollKey = screen === 'quiz' ? `quiz-${active?.id}-${active?.cursor}`
    : ['detail', 'question', 'report', 'share'].includes(screen) ? `${screen}-${recordId}-${screen === 'question' ? qid : ''}`
    : screen === 'wrong' ? `wrong-${wrongKey}` : screen
  const go = (next: Screen) => {
    if (next !== screen) {
      stack.current.push(screen)
      setScreen(next)
    }
    setExpanded(false)
  }
  const root = (next: Screen) => {
    if (screenRef.current === 'reportLoading') {
      token.current++
      busy.current = false
    }
    stack.current = []
    setScreen(next)
    setPaused(false)
  }
  const back = () => {
    if (screen === 'quiz') {
      setPaused(true)
      return
    }
    if (screen === 'generating') {
      cancel()
      return
    }
    if (screen === 'reportLoading') {
      token.current++
      root('review')
      return
    }
    setScreen(stack.current.pop() || 'home')
    setExpanded(false)
  }
  const future = (name: string) =>
    setDialog({
      title: '这条路，正在准备',
      message: `${name}将在后续版本开放。现在可以先从文字输入开始，完成一关学习。`,
    })
  function openRecord(s: Session, next: Screen = 'detail') {
    setRecordId(s.id)
    go(next)
  }
  function openSession(s: Session) {
      upsert(s)
      setRecordId(s.id)
      setSelected([])
      setExpanded(false)
      setScreen(s.mode === 'review' ? 'quiz' : 'ready')
      stack.current = []
  }
  async function createSession(quiz: Quiz, mode: Session['mode'] = 'replay') {
    if (busy.current) return
    busy.current = true
    try { openSession(await replayQuiz(quiz.id)) }
    catch (e) { setDialog({ title: '暂时无法开始', message: (e as Error).message }) }
    finally { busy.current = false }
  }
  async function start() {
    if (!data.draft.text.trim() || busy.current || cloudLoading) return
    busy.current = true
    const ticket = ++token.current
    setScreen('generating')
    try {
      const signature = JSON.stringify(data.draft)
      if (quizOperation.current?.signature !== signature) quizOperation.current = { signature, key: operationKey() }
      const session = await generateQuiz(data.draft.text, data.draft.count, data.draft.difficulty, quizOperation.current!.key)
      quizOperation.current = undefined
      if (token.current === ticket) openSession(session)
      void api<User>('/api/v1/me').then(auth.update).catch(() => {})
    } catch (e) {
      if (!(e instanceof ApiError) || !['NETWORK_ERROR', 'AI_BUSY'].includes(e.code)) quizOperation.current = undefined
      if (token.current === ticket) {
        setError({ message: (e as Error).message, kind: 'quiz' })
        setScreen('error')
      }
    } finally {
      if (token.current === ticket) busy.current = false
    }
  }
  function cancel() {
    token.current++
    cancelRequest()
    busy.current = false
    root('home')
  }
  async function submit(values: string[]) {
    if (!active || !current || answered || busy.current) return
    busy.current = true
    setQuestionBusy(true)
    setSelected(values)
    try {
      const result = await submitAnswer(active.id, current.id, values, active.pending_ms)
      upsert(result.session)
      auth.update(result.user)
      setSelected(values)
      setExpanded(false)
      void refresh(true).catch(() => {})
    } catch (e) { setDialog({ title: '答案尚未确认', message: (e as Error).message + ' 请保留当前选择并重新提交。' }) }
    finally { busy.current = false; setQuestionBusy(false) }
  }
  function choose(value: string) {
    if (answered || busy.current) return
    if (current?.type === 'multi')
      setSelected((old) => {
        const next = old.includes(value) ? old.filter((x) => x !== value) : [...old, value]
        selectionDrafts.current[`${active!.id}:${current.id}`] = next
        return next
      })
    else submit([value])
  }
  async function jumpQuestion(index: number) {
    if (!active || !current || busy.current || index === active.cursor || index < 0 || index >= active.quiz.questions.length) return
    busy.current = true
    setQuestionBusy(true)
    answerTimes.current[`${active.id}:${current.id}`] = active.pending_ms
    try {
      const session = await saveProgress(active.id, index)
      const key = `${active.id}:${session.quiz.questions[index].id}`
      upsert({ ...session, pending_ms: answerTimes.current[key] || 0 })
      setSelected(selectionDrafts.current[key] || [])
      setExpanded(false)
    } catch (e) { setDialog({ title: '进度尚未确认', message: (e as Error).message }) }
    finally { busy.current = false; setQuestionBusy(false) }
  }
  function finishQuiz() {
    if (!active || busy.current || active.answers.length !== active.quiz.questions.length) return
    setRecordId(active.id)
    setScreen(active.mode === 'review' ? 'reviewResult' : 'result')
  }
  async function reportFor(s: Session) {
    setRecordId(s.id)
    if (s.report) {
      go('report')
      return
    }
    if (busy.current) return
    busy.current = true
    const ticket = ++token.current
    go('reportLoading')
    try {
      const key = reportOperations.current[s.id] || (reportOperations.current[s.id] = operationKey())
      const report = await generateReport(s, key)
      delete reportOperations.current[s.id]
      if (dispatch({ type: 'REPORT', id: s.id, report }) && token.current === ticket)
        setScreen('report')
    } catch (e) {
      if (!(e instanceof ApiError) || !['NETWORK_ERROR', 'AI_BUSY'].includes(e.code)) delete reportOperations.current[s.id]
      if (token.current === ticket) {
        setError({ message: (e as Error).message, kind: 'report' })
        setScreen('error')
      }
    } finally {
      if (token.current === ticket) busy.current = false
    }
  }
  function resume(s: Session) {
    dispatch({ type: 'ACTIVE', id: s.id })
    setRecordId(s.id)
    setSelected([])
    setScreen(s.completed_at ? (s.mode === 'review' ? 'reviewResult' : 'result') : 'quiz')
  }
  async function review(items: Wrong[]) {
    if (!items.length || busy.current) return
    busy.current = true
    try { openSession(await reviewWrongs(items.map(w => w.key))) }
    catch (e) { setDialog({ title: '暂时无法开始复习', message: (e as Error).message }) }
    finally { busy.current = false }
  }
  function openWrong(w: Wrong) {
    setWrongKey(w.key)
    go('wrong')
  }
  async function save() {
    if (!record || saving) return
    setSaving(true)
    try {
      const path = poster || (await makePoster(record))
      setPoster(path)
      await savePoster(path)
      void Taro.showToast({
        title: process.env.TARO_ENV === 'h5' ? '已下载海报' : '已保存到相册',
        icon: 'success',
      })
    } catch (e) {
      setDialog({ title: '海报还在这里', message: (e as Error).message })
    } finally {
      setSaving(false)
    }
  }
  async function exportRecords() {
    try {
      await saveExport(await getLearning())
    } catch (e) {
      setDialog({ title: '导出暂时未完成', message: (e as Error).message })
    }
  }
  useEffect(() => {
    const p = Taro.getCurrentInstance().router?.params
    try {
      if (p?.topic) {
        const topic = decodeURIComponent(p.topic).slice(0, 80)
        dispatch({ type: 'DRAFT', draft: { ...data.draft, text: topic } })
        dispatch({ type: 'WELCOME' })
        root('home')
      }
    } catch {}
  }, [])
  useEffect(() => {
    setPoster('')
  }, [recordId])
  useEffect(() => {
    if (screen !== 'quiz' || paused || answered || questionBusy) return
    const timer = setInterval(() => {
      if (visible.current) dispatch({ type: 'TICK', ms: 1000 })
    }, 1000)
    return () => clearInterval(timer)
  }, [screen, paused, active?.id, active?.cursor, !!answered, questionBusy])
  useDidHide(() => {
    visible.current = false
    if (screenRef.current === 'quiz') setPaused(true)
  })
  useDidShow(() => {
    visible.current = true
  })
  useShareAppMessage(() => ({
    title: `一起搞懂：${(record?.quiz.title || data.draft.text || '今天的好奇心').slice(0, 30)}`,
    path: `/pages/index/index?topic=${encodeURIComponent((record?.quiz.title || data.draft.text).slice(0, 60))}`,
  }))

  const id =
    screen === 'quiz'
      ? paused
        ? 'L14'
        : active?.mode === 'review'
          ? 'R11'
          : current?.type === 'multi'
            ? 'L10'
            : current?.type === 'judge'
              ? 'L11'
              : 'L09'
      : screen === 'home' && !data.draft.text
        ? 'L20'
        : screen === 'error' && error.kind === 'report'
          ? 'E07'
          : baseIds[screen]
  const refined = !['home', 'review', 'history', 'analytics', 'mine', 'settings', 'data'].includes(
    screen,
  )
  let body: React.ReactNode = null,
    footer: React.ReactNode = null
  const empty = (title: string, sub: string, action?: () => void) => (
    <>
      <View className="empty-illustration">
        <Mascot who="paper" />
      </View>
      <View className="center">
        <Title sub={sub}>{title}</Title>
      </View>
      {action && (
        <View className="mt">
          <Btn onClick={action}>开始我的第一关</Btn>
        </View>
      )}
    </>
  )
  const rewards = (s: Session) => (
    <View className="reward-row">
      <Text className="reward">
        <Icon name="bolt" />+{stats(s).xp} XP
      </Text>
      <Text className="reward">
        <Icon name="coin" />+{stats(s).coins} 金币
      </Text>
    </View>
  )
  const feedback = (q: Question, a: string[]) => {
    const ok = isCorrect(q, a)
    return (
      <View className={`feedback ${ok ? '' : 'wrong'}`}>
        <View className="feedback-heading">
          <Icon name={ok ? 'check' : 'help'} />
          {ok ? '答对了，思路很清楚！' : '这题有个小转弯'}
        </View>
        <View className="feedback-copy">
          <Text className="strong">正确答案：{q.answers.join('、')}</Text>
          <View>
            {expanded
              ? q.explanation
              : q.explanation.slice(0, 180) + (q.explanation.length > 180 ? '…' : '')}
          </View>
        </View>
        {q.explanation.length > 180 && (
          <View className="text-btn" onClick={() => setExpanded(!expanded)}>
            {expanded ? '收起完整讲解' : '展开完整讲解'}
          </View>
        )}
        <View className="source-note">根据输入材料与模型知识生成 · 建议结合原始资料核实</View>
      </View>
    )
  }
  const rows = (sessions: Session[]) =>
    sessions.map((s) => (
      <Row
        key={s.id}
        title={s.quiz.title}
        sub={`${when(s.completed_at || s.started_at)} / ${s.quiz.questions.length} 题 / 正确率 ${stats(s).accuracy}%`}
        end={<Tag color="blue">{s.mode === 'replay' ? '重闯' : '已通关'}</Tag>}
        onClick={() => openRecord(s)}
      />
    ))

  if (screen === 'welcome') {
    body = (
      <View className="center" style={{ paddingTop: 28 }}>
        <View className="brand">
          <Text className="brand-mark">U</Text>LevelUProject
        </View>
        <View className="page-title" style={{ marginTop: 32, fontSize: 32, lineHeight: 1.45 }}>
          把好奇心，{`\n`}变成你的<Text className="handline">下一关。</Text>
        </View>
        <View className="index-art" style={{ height: 230, marginTop: 25 }}>
          <Mascot who="pencil" className="pencil" />
          <Mascot className="u" />
          <Mascot who="paper" className="paper" />
        </View>
        <View className="body-copy mt">一句话、一份笔记。{`\n`}问一问，答一答，就懂了一点。</View>
        <View className="tags mt" style={{ justifyContent: 'center' }}>
          <Tag color="blue">小U / 知识引导</Tag>
          <Tag color="yellow">笔仔 / 答题搭子</Tag>
          <Tag>团团 / 复盘探索</Tag>
        </View>
      </View>
    )
    footer = (
      <>
        <Btn
          onClick={() => {
            if (dispatch({ type: 'WELCOME' })) root('home')
          }}
        >
          先体验一关
        </Btn>
        <Btn secondary onClick={() => future('微信登录与云同步')}>
          微信登录，保存学习档案
        </Btn>
      </>
    )
  }
  if (screen === 'home') {
    const draft = data.draft,
      incomplete = data.sessions
        .filter((s) => !s.completed_at)
        .slice()
        .reverse()
    body = (
      <>
        <View className="row">
          <Text className="kicker">你好，学习搭子</Text>
          <Text className="xp" onClick={() => future('搭子装扮')}>
            <Icon name="coin" />
            {profile.coins} 金币
          </Text>
        </View>
        <Hero sub={draft.text ? '一个问题，就是一关。' : '让搭子帮你拆成几个好问题。'}>
          {draft.text ? (
            <>
              今天想{`\n`}
              <Text className="handline">搞懂什么？</Text>
            </>
          ) : (
            <>好奇什么，{`\n`}就学什么。</>
          )}
        </Hero>
        <View className="notebook">
          <Textarea
            value={draft.text}
            maxlength={5000}
            placeholder="比如：HTTP 为什么是无状态的？"
            onInput={(e) => dispatch({ type: 'DRAFT', draft: { ...draft, text: e.detail.value } })}
            autoHeight={false}
          />
          <View className="input-foot">
            <Text>{draft.text ? '主题、笔记，都可以放进来' : '也可以粘贴一段学习笔记'}</Text>
            <Text>{draft.text.length} / 5000</Text>
          </View>
        </View>
        <View className="material-grid">
          {[
            ['file', '文档'],
            ['link', '网页'],
            ['video', '视频'],
          ].map(([icon, name]) => (
            <View key={name} className="material" onClick={() => future(`${name}解析`)}>
              <Icon name={icon} />
              {name}
            </View>
          ))}
        </View>
        <View className="config-summary" onClick={() => setConfig(!config)}>
          <Text>{config ? '▾' : '▸'} 出题设置</Text>
          <Text className="small muted">
            {draft.count} 题 / {draft.difficulty === 'easy' ? '入门' : '进阶'}
          </Text>
        </View>
        {config && (
          <>
            <View className="config-row">
              <Text>题量</Text>
              <Chips
                items={['5 题', '3 题']}
                value={draft.count === 5 ? 0 : 1}
                onChange={(i) => dispatch({ type: 'DRAFT', draft: { ...draft, count: i ? 3 : 5 } })}
              />
            </View>
            <View className="config-row">
              <Text>难度</Text>
              <Chips
                items={['入门', '进阶']}
                value={draft.difficulty === 'easy' ? 0 : 1}
                onChange={(i) =>
                  dispatch({
                    type: 'DRAFT',
                    draft: { ...draft, difficulty: i ? 'medium' : 'easy' },
                  })
                }
              />
            </View>
          </>
        )}
        <Btn disabled={!draft.text.trim() || cloudLoading} onClick={start}>
          生成我的关卡 <Icon name="spark-white" />
        </Btn>
        <View className="small muted mt">今天还可生成 {auth.user.quota.remaining} / {auth.user.quota.daily_limit} 个新关卡</View>
        <Section>{draft.text ? '换个脑洞试试' : '没有灵感？从这里开始'}</Section>
        <View className="example-chips">
          {['HTTP 为什么是无状态的？', '什么是复利？', '怎么理解条件概率？'].map((text) => (
            <Text key={text} onClick={() => dispatch({ type: 'DRAFT', draft: { ...draft, text } })}>
              {text === 'HTTP 为什么是无状态的？' ? '认识 HTTP' : text}
            </Text>
          ))}
        </View>
        {incomplete.length > 0 && (
          <>
            <Section>接着上次的好奇心</Section>
            {incomplete.map((s) => (
              <Row
                key={s.id}
                title={s.quiz.title}
                sub={`已完成 ${s.answers.length} / ${s.quiz.questions.length} 题`}
                end={<Tag color="blue">继续</Tag>}
                onClick={() => resume(s)}
              />
            ))}
          </>
        )}
        {profile.completed.length > 0 ? (
          <>
            <Section link="学习记录" onClick={() => go('history')}>
              上次的好奇心
            </Section>
            {rows(profile.completed.slice(-2).reverse())}
          </>
        ) : (
          <Buddy>问题不用很专业，想知道什么就写什么。</Buddy>
        )}
      </>
    )
  }
  if (screen === 'generating') {
    body = (
      <>
        <Stage sticker="把好奇心，拆成好问题" />
        <Title sub="根据你输入的文字，整理一关属于你的学习。">
          你的关卡，<Text className="handline">正在成形</Text>
        </Title>
        <View className="steps mt">
          {[
            ['学习材料已收到', '只使用本次输入的文字'],
            ['正在出题与整理讲解', 'AI 生成后会校验题型与答案'],
            ['准备你的学习关卡', '无需联网检索其他材料'],
          ].map(([title, sub], i) => (
            <View className="step" key={title}>
              <View className="step-dot">{i === 0 ? '✓' : i + 1}</View>
              <View>
                <View className="step-title">{title}</View>
                <View className="step-sub">{sub}</View>
              </View>
            </View>
          ))}
        </View>
        <View className="hint-note">生成可能需要一点时间。取消后，输入内容仍会保留。</View>
      </>
    )
    footer = (
      <Btn secondary onClick={cancel}>
        取消生成，返回修改
      </Btn>
    )
  }
  if (screen === 'ready' && active) {
    body = (
      <>
        <Stage who="pencil" sticker="准备好开窍了吗？" yellow />
        <Title sub={`${active.quiz.questions.length} 个小问题，拆开一个大概念。`}>
          {active.quiz.title}，<Text className="handline">认识一下</Text>
        </Title>
        <Stat
          items={[
            [active.quiz.questions.length, '道题'],
            [`约 ${Math.ceil(active.quiz.questions.length * 0.6)} 分钟`, '预计用时'],
            [active.quiz.difficulty === 'easy' ? '入门' : '进阶', '难度'],
          ]}
        />
        <View className="panel">
          <View className="row mb">
            <Tag color="blue">本轮路线</Tag>
            <Icon name="flag" />
          </View>
          <View className="tags">
            {[...new Set(active.quiz.questions.map((q) => q.knowledge_point))].map((point) => (
              <Tag key={point}>{point}</Tag>
            ))}
          </View>
          <View className="small muted mt">
            单选、多选、判断。每题答完都有讲解，答错也能学到东西。
          </View>
        </View>
        <View className="small muted mt">
          {active.mode === 'new'
            ? `每题首次答对 +${rewardRate(active.quiz).xp} XP、+${rewardRate(active.quiz).coins} 金币；答错不扣已有奖励。`
            : '这是重闯，保留练习记录，不重复发放奖励。'}
        </View>
      </>
    )
    footer = <Btn onClick={() => go('quiz')}>开始这一关</Btn>
  }
  if (screen === 'quiz' && active && current) {
    const a = answered?.selected,
      ok = a ? isCorrect(current, a) : false,
      v = stats(active)
    body = (
      <>
        <View className="quiz-progress">
          <Text>
            {active.cursor + 1} / {active.quiz.questions.length}
          </Text>
          <View className="quiz-steps" role="navigation" aria-label="切换题目">
            {active.quiz.questions.map((q, index) => (
              <View key={q.id} role="button" aria-label={`第 ${index + 1} 题`} aria-current={index === active.cursor ? 'step' : undefined}
                className={`quiz-step ${index === active.cursor ? 'current' : ''} ${active.answers.some(answer => answer.question_id === q.id) ? 'answered' : ''}`}
                onClick={() => void jumpQuestion(index)}>
                <Text className="quiz-step-number">{index + 1}</Text>
              </View>
            ))}
          </View>
          <Text className="xp">
            <Icon name="bolt" />
            {v.xp} XP
          </Text>
        </View>
        <View className="question-meta">
          <Tag color={active.mode === 'review' ? 'yellow' : 'blue'}>
            {active.mode === 'review' ? '旧识重温 / ' : ''}
            {typeName(current.type)}
          </Tag>
          <Text className="muted">{active.mode === 'review' ? '旧识重温' : active.quiz.title}</Text>
        </View>
        <View className="question">{current.stem}</View>
        <View className={current.type === 'judge' ? 'judge-grid' : 'option-list'}>
          {current.options.map((o) => (
            <View
              role="button"
              key={o.id}
              className={`option ${current.type === 'judge' ? 'judge' : ''} ${a ? (current.answers.includes(o.id) ? 'correct' : a.includes(o.id) ? 'incorrect' : '') : selected.includes(o.id) ? 'selected' : ''}`}
              onClick={() => choose(o.id)}
            >
              {current.type === 'judge' ? (
                <Icon name={o.id === 'A' ? 'check' : 'close'} />
              ) : (
                <Text className="option-code">{o.id}</Text>
              )}
              <Text className="option-copy">{o.text}</Text>
              {a && (
                <Text className="answer-status">
                  {current.answers.includes(o.id) ? '正确' : a.includes(o.id) ? '你的答案' : ''}
                </Text>
              )}
            </View>
          ))}
        </View>
        {a ? (
          <>
            {feedback(current, a)}
            {ok && active.mode === 'new' ? (
              <View className="reward-row">
                <Text className="reward">+{rewardRate(active.quiz).xp} XP</Text>
                <Text className="reward">+{rewardRate(active.quiz).coins} 金币</Text>
              </View>
            ) : (
              !ok && (
                <View className="small muted mt">
                  {active.mode === 'new'
                    ? '已记入错题本，本题不获得奖励。'
                    : '这次没选对，再看一遍讲解。'}
                </View>
              )
            )}
            {active.answers.length >= 3 &&
              active.answers.slice(-3).every((answer) =>
                isCorrect(
                  active.quiz.questions.find((q) => q.id === answer.question_id)!,
                  answer.selected,
                ),
              ) && <View className="quiz-toast">连续答对 3 题，知识开始串起来了！</View>}
          </>
        ) : (
          <View className="question-hint">
            <Icon name={current.type === 'multi' ? 'help' : 'bolt'} />
            {current.type === 'multi' ? '选择所有符合条件的选项' : '选择后立即查看答案与讲解'}
          </View>
        )}
      </>
    )
    footer = <>
      {!a && current.type === 'multi' && <View className="quiz-submit"><Btn disabled={!selected.length || questionBusy} onClick={() => submit(selected)}>提交答案</Btn></View>}
      <View className="quiz-navigation">
        <Btn secondary disabled={active.cursor === 0 || questionBusy} onClick={() => void jumpQuestion(active.cursor - 1)}>上一题</Btn>
        <Btn disabled={active.cursor === active.quiz.questions.length - 1 || questionBusy} onClick={() => void jumpQuestion(active.cursor + 1)}>下一题</Btn>
      </View>
      {active.answers.length === active.quiz.questions.length
        ? <View className="quiz-finish"><Btn disabled={questionBusy} onClick={finishQuiz}>完成这一关</Btn></View>
        : <View className="small muted center quiz-completion">已答 {active.answers.length} / {active.quiz.questions.length} 题，全部作答后可完成本关</View>}
    </>
  }
  if ((screen === 'result' || screen === 'reviewResult') && record && sStats) {
    const reviewDone = screen === 'reviewResult'
    body = (
      <>
        <Stage
          who={reviewDone ? 'paper' : 'pencil'}
          sticker={reviewDone ? '旧知识，新理解' : '这一关，拿下！'}
          yellow
        />
        <View className="center">
          <Title>
            {reviewDone ? (
              <>
                旧知识，有了<Text className="handline">新理解</Text>
              </>
            ) : (
              <>
                又<Text className="handline">搞懂了一点</Text>！
              </>
            )}
          </Title>
          <View className="small muted">{record.quiz.title} / 本轮完成</View>
          <View className="result-score mt">
            {sStats.accuracy}
            <Text className="score-unit">%</Text>
          </View>
          <View className="small muted">本轮正确率</View>
        </View>
        <Stat
          items={[
            [`${sStats.correct_count} / ${sStats.total}`, '答对题数'],
            [duration(sStats.duration_ms), '学习用时'],
            [sStats.knowledge_points.length, '知识点'],
          ]}
        />
        {rewards(record)}
        <Buddy who={reviewDone ? 'paper' : 'pencil'}>
          {reviewDone
            ? '答对的错题已移入「已掌握」，历史答案仍会保留。'
            : '这次会了，下次遇见它就更有底气。'}
        </Buddy>
      </>
    )
    footer = reviewDone ? (
      <>
        <Btn onClick={() => root('wrongs')}>回到错题本</Btn>
        <Btn secondary onClick={() => root('home')}>
          探索一个新主题
        </Btn>
      </>
    ) : (
      <>
        <Btn onClick={() => reportFor(record)}>看看这关学到了什么</Btn>
        <Btn secondary onClick={() => root('home')}>
          再学一个新主题
        </Btn>
      </>
    )
  }
  if (screen === 'reviewResult' && record && sStats) {
    const remaining = record.quiz.questions.filter(
      (q) => !sStats.results.find((r) => r.question_id === q.id)?.is_correct,
    )
    body = (
      <>
        <Stage who="paper" sticker="又清楚了一点！" />
        <Title>
          旧知识，<Text className="handline">新理解</Text>
        </Title>
        <View className="body-copy center">这次重温，{`\n`}有些模糊的地方变清楚了。</View>
        <Stat
          items={[
            [sStats.correct_count, '已巩固'],
            [sStats.total - sStats.correct_count, '仍需复习'],
            [duration(sStats.duration_ms), '本次用时'],
          ]}
        />
        <View className="panel yellow">
          <View className="strong">
            {remaining.length
              ? remaining[0].knowledge_point + '，再看看'
              : '这一轮旧知识，又清楚了一点'}
          </View>
          <View className="small muted mt">
            {remaining.length
              ? '可以再看一遍讲解，然后用自己的话解释一次。'
              : '答对的错题已移入「已掌握」。'}
          </View>
        </View>
        <View className="small muted mt">
          原始错题记录保留；重温更新复习状态，不重复发放本轮关卡奖励。
        </View>
      </>
    )
    footer = (
      <>
        <Btn onClick={() => root('wrongs')}>返回错题本</Btn>
        <Btn secondary onClick={() => root('home')}>
          继续探索新知识
        </Btn>
      </>
    )
  }
  if (screen === 'reportLoading' && record && sStats) {
    body = (
      <>
        <Title sub="答题记录已保存，正在把这一关变成你的知识笔记。">
          收获，<Text className="handline">正在整理</Text>
        </Title>
        <Stat
          items={[
            [`${sStats.accuracy}%`, '正确率'],
            [`${sStats.correct_count} / ${sStats.total}`, '答对题数'],
            [sStats.xp, '本轮 XP'],
          ]}
        />
        <Stage sticker="写一份属于你的总结" />
        <View className="steps">
          {[
            ['基础数据已保存', '可以随时在历史记录查看'],
            ['整理知识与薄弱点', '根据本轮答案生成学习建议'],
            ['完成复盘报告', '支持逐题回看和分享'],
          ].map(([title, sub], i) => (
            <View className="step" key={title}>
              <View className="step-dot">{i ? i + 1 : '✓'}</View>
              <View>
                <View className="step-title">{title}</View>
                <View className="step-sub">{sub}</View>
              </View>
            </View>
          ))}
        </View>
      </>
    )
    footer = (
      <Btn secondary onClick={() => root('history')}>
        先去学习记录看看
      </Btn>
    )
  }
  if (screen === 'report' && record?.report && sStats) {
    const report = record.report
    body = (
      <>
        <Tag color="blue">本轮学习报告</Tag>
        <View className="mt">
          <Title>{record.quiz.title}</Title>
        </View>
        <View className="small muted mb">
          {when(record.completed_at || record.started_at)} / {sStats.total} 道题
        </View>
        <View className="report-intro">
          <View
            className="ring"
            style={{ background: `conic-gradient(#336ae8 ${sStats.accuracy}%,#e8edf5 0)` }}
          >
            <View className="ring-inner">
              <Text className="ring-value">{sStats.accuracy}%</Text>
              <Text className="ring-label">本轮正确率</Text>
            </View>
          </View>
          <View>
            <View className="report-heading">
              {sStats.accuracy === 100
                ? '这一关，理解得很清楚'
                : sStats.accuracy >= 60
                  ? '基本概念，已拿稳'
                  : '再遇见一次，会更清楚'}
            </View>
            <View className="body-copy">
              {report.weak_points.length
                ? report.weak_points.join('、') + '值得再巩固一下。'
                : '试着用自己的话，解释一次。'}
            </View>
          </View>
        </View>
        <Section>三句话，带走这关</Section>
        <View className="takeaway">
          {report.summary.map((line, i) => (
            <View className="takeaway-line" key={i}>
              {line}
            </View>
          ))}
        </View>
        <Section>知识点掌握 · 本轮估计</Section>
        {sStats.knowledge_points.map((p) => (
          <Mastery
            key={p.name}
            label={p.name}
            value={p.accuracy}
            color={p.accuracy >= 80 ? 'green' : 'yellow'}
          />
        ))}
        <View className="small muted">仅根据本轮少量题目估计，不代表长期能力。</View>
        <Section>下一步，可以这样学</Section>
        <View className="report-list">
          {report.suggestions.map((x, i) => (
            <View key={i}>
              {i + 1}. {x}
            </View>
          ))}
        </View>
        <Row
          title="再巩固一下薄弱知识"
          sub={`${sStats.total - sStats.correct_count} 道本轮错题`}
          icon="refresh"
          onClick={() => go('wrongs')}
          textLed
        />
        <Row
          title="逐题回看"
          sub={`查看 ${sStats.total} 道题的答案和讲解`}
          onClick={() => go('detail')}
          textLed
        />
      </>
    )
    footer = (
      <>
        <Btn onClick={() => go('share')}>
          <Icon name="share" />
          分享这次收获
        </Btn>
        <View className="text-btn" onClick={() => root('review')}>
          前往个人学习中心
        </View>
      </>
    )
  }
  if (screen === 'share' && record && sStats) {
    body = (
      <>
        <Title sub="分享的是你学到的东西。">
          把收获，<Text className="handline">分享出去</Text>
        </Title>
        <View className="poster mt">
          <View className="brand">
            <Text className="brand-mark">U</Text>LevelUProject
          </View>
          <View className="poster-title">
            今天，我搞懂了{`\n`}
            {record.quiz.title}
          </View>
          <View className="poster-quote">
            “{record.report?.share_quote || '每个问题，都是理解的起点。'}”
          </View>
          <Crew />
          <View className="row">
            <View className="poster-footer">
              {sStats.total} 个问题，带走 {sStats.knowledge_points.length} 个知识点
              <View className="small muted">和我一起，给好奇心升个级。</View>
            </View>
            {MINI_CODE_URL ? (
              <Image src={MINI_CODE_URL} className="code-image" />
            ) : (
              <View className="code-placeholder">小程序码{`\n`}待配置</View>
            )}
          </View>
        </View>
        <View className="notice">
          <Icon name="help" />
          {process.env.TARO_ENV === 'h5'
            ? '可下载真实 PNG 海报；好友卡片请在微信小程序使用。'
            : '好友会从这个主题开始，独立生成自己的关卡。'}
        </View>
        <Canvas type="2d" id="poster-canvas" canvasId="poster-canvas" className="canvas-hidden" />
      </>
    )
    footer = (
      <>
        <Btn onClick={save} disabled={saving}>
          <Icon name="download" />
          {saving ? '正在生成海报…' : '保存海报图片'}
        </Btn>
        <Btn
          secondary
          share={process.env.TARO_ENV === 'weapp'}
          onClick={
            process.env.TARO_ENV === 'h5'
              ? () =>
                  setDialog({
                    title: '在微信里，叫上朋友',
                    message:
                      '当前为 H5 验收预览。微信构建已实现同主题卡片分享，可在微信开发工具和真机中验证。',
                  })
              : undefined
          }
        >
          邀请好友学同一主题
        </Btn>
      </>
    )
  }
  if (screen === 'review')
    body = (
      <>
        <Hero sub="今天也给旧知识一点关注。" who="paper">
          学过的，{`\n`}
          <Text className="handline">慢慢变成自己的。</Text>
        </Hero>
        <Stat
          items={[
            [profile.topics, '学过主题'],
            [pending.length, '待复习'],
            [`${profile.streak} 天`, '连续学习'],
          ]}
        />
        <View className="comic-panel blue">
          <View className="row">
            <View>
              <Text className="strong">今日重温计划</Text>
              <View className="small muted">
                {pending.length} 道旧题 / 约 {Math.ceil(pending.length / 2)} 分钟
              </View>
            </View>
            <Icon name="refresh" />
          </View>
          <View className="mt">
            <Btn disabled={!pending.length} onClick={() => go('queue')}>
              开始旧识重温
            </Btn>
          </View>
        </View>
        <Section>复盘工具</Section>
        <View className="material-grid">
          {[
            ['book', '错题本'],
            ['spark', '知识地图'],
            ['chart', '数据分析'],
          ].map(([icon, name], i) => (
            <View
              key={name}
              className="material"
              onClick={() => (i === 1 ? future(name) : go(i === 0 ? 'wrongs' : 'analytics'))}
            >
              <Icon name={icon} />
              {name}
            </View>
          ))}
        </View>
        <Section link="查看全部" onClick={() => go('history')}>
          最近学过
        </Section>
        {profile.completed.length
          ? rows(profile.completed.slice(-3).reverse())
          : empty(
              '第一份学习记录，\n从一个问题开始。',
              '写下今天想懂的东西，搭子帮你变成一关。',
              () => root('home'),
            )}
      </>
    )
  if (screen === 'history') {
    const list = data.sessions
      .filter(
        (s) =>
          s.completed_at &&
          s.mode !== 'review' &&
          inHistoryRange(s.completed_at, historyRange) &&
          (s.quiz.title + ' ' + s.quiz.questions.map((q) => q.knowledge_point).join(' '))
            .toLowerCase()
            .includes(search.toLowerCase()),
      )
      .reverse()
    body = (
      <>
        <Title>每一次好奇，都有记录</Title>
        <Input
          className="input search-input"
          placeholder="搜索主题或知识点"
          value={search}
          onInput={(e) => setSearch(e.detail.value)}
        />
        <Segments
          items={['全部', '本周', '本月']}
          value={historyRange}
          onChange={setHistoryRange}
        />
        {list.length
          ? rows(list)
          : empty('这里，还没有学习记录', '完成一关后，就会留下自己的收获。', () => root('home'))}
        <View className="small muted mt">已显示 {list.length} 条本机记录。</View>
      </>
    )
  }
  if (screen === 'detail' && record && sStats) {
    body = (
      <>
        <Tag color="green">已通关</Tag>
        <Title>{record.quiz.title}</Title>
        <View className="small muted">
          {when(record.started_at)} / 文本输入{record.mode === 'replay' ? ' / 重闯' : ''}
        </View>
        <Stat
          items={[
            [`${sStats.accuracy}%`, '正确率'],
            [duration(sStats.duration_ms), '用时'],
            [sStats.xp, '获得 XP'],
          ]}
        />
        <Row
          title={record.report ? '查看本轮复盘报告' : '生成本轮复盘报告'}
          sub="知识总结与薄弱点建议"
          icon="chart"
          onClick={() => reportFor(record)}
          textLed
        />
        <Section>逐题记录</Section>
        <View className="question-records">
          {record.answers.map((a) => {
            const q = record.quiz.questions.find((x) => x.id === a.question_id)!,
              ok = isCorrect(q, a.selected)
            return (
              <Row
                key={q.id}
                icon={{ single: 'choice-single', multi: 'choice-multi', judge: 'judge' }[q.type]}
                iconLabel={typeName(q.type)}
                title={q.stem}
                sub={`你的答案 ${a.selected.join('、')} / 正确答案 ${q.answers.join('、')}`}
                end={<Tag color={ok ? 'green' : 'red'}>{ok ? '正确' : '错误'}</Tag>}
                onClick={() => {
                  setQid(q.id)
                  go('question')
                }}
              />
            )
          })}
        </View>
        <Section>原始学习材料</Section>
        <View className="body-copy">{record.quiz.source_text}</View>
        <View className="source-note">本轮题库已保存在本机，可离线回看。</View>
      </>
    )
    footer = <Btn onClick={() => createSession(record.quiz, 'replay')}>再闯一次这一关</Btn>
  }
  if (screen === 'question' && record) {
    const q = record.quiz.questions.find((q) => q.id === qid),
      a = record.answers.find((a) => a.question_id === qid)
    if (q && a)
      body = (
        <>
          <Tag color="blue">
            {typeName(q.type)} / {record.quiz.title}
          </Tag>
          <View className="question">{q.stem}</View>
          <View className="panel blue answer-detail">
            <View>你的答案：{optionText(q, a.selected)}</View>
            <View className="mt">正确答案：{optionText(q, q.answers)}</View>
          </View>
          {feedback(q, a.selected)}
          <Section>全部选项</Section>
          {q.options.map((o) => (
            <View className="answer-detail mt" key={o.id}>
              {o.id}. {o.text}
            </View>
          ))}
        </>
      )
  }
  if (screen === 'analytics') {
    const list = profile.completed.filter((s) =>
        inRange(s.completed_at!, [7, 30, 0][analyticsRange]),
      ),
      sum = list.reduce(
        (v, s) => {
          const t = stats(s)
          return {
            correct: v.correct + t.correct_count,
            total: v.total + t.total,
            time: v.time + t.duration_ms,
          }
        },
        { correct: 0, total: 0, time: 0 },
      )
    const daily = Array.from({ length: analyticsRange === 1 ? 30 : 7 }, (_, i) => {
      const day = new Date()
      day.setDate(day.getDate() - (analyticsRange === 1 ? 29 : 6) + i)
      const dayList = list.filter(
          (s) => new Date(s.completed_at!).toDateString() === day.toDateString(),
        ),
        count = dayList.reduce((n, s) => n + s.quiz.questions.length, 0),
        correct = dayList.reduce((n, s) => n + stats(s).correct_count, 0)
      return {
        label: `${day.getMonth() + 1}/${day.getDate()}`,
        count,
        accuracy: count ? (correct / count) * 100 : null,
      }
    })
    const trend =
      analyticsRange === 2
        ? list.slice(-15).map((s) => ({
            label: when(s.completed_at!).split(' ')[0],
            accuracy: stats(s).accuracy,
            count: s.quiz.questions.length,
          }))
        : daily
    body = (
      <>
        <Title>看见自己的进步</Title>
        <Segments
          items={['近 7 天', '近 30 天', '全部']}
          value={analyticsRange}
          onChange={setAnalyticsRange}
        />
        <View className="row">
          <Tag>本机新学记录</Tag>
          <Text className="text-btn" onClick={() => future('周期报告')}>
            生成报告 <Icon name="chevron" />
          </Text>
        </View>
        <Stat
          items={[
            [`${sum.total ? Math.round((sum.correct / sum.total) * 100) : 0}%`, '平均正确率'],
            [sum.total, '完成题数'],
            [`${Math.round(sum.time / 60000)} 分钟`, '学习用时'],
          ]}
        />
        <Section>正确率趋势</Section>
        {!sum.total ? (
          <View className="hint-note">完成第一关后，这里会显示真实趋势。</View>
        ) : (
          <Trend points={trend} />
        )}
        <Section>题型表现</Section>
        {(['single', 'multi', 'judge'] as const).map((type) => {
          const qs = list.flatMap((s) =>
              s.quiz.questions
                .filter((q) => q.type === type)
                .map((q) => ({ q, a: s.answers.find((a) => a.question_id === q.id)! })),
            ),
            correct = qs.filter((x) => isCorrect(x.q, x.a.selected)).length
          return (
            <Mastery
              key={type}
              label={`${typeName(type)} / ${qs.length} 题`}
              value={qs.length ? Math.round((correct / qs.length) * 100) : 0}
              color={type === 'multi' ? 'yellow' : 'green'}
            />
          )
        })}
        <Section>最近一周学习量 · 题</Section>
        <View className="bar-grid">
          {daily.slice(-7).map((d) => (
            <View className="bar-col" key={d.label}>
              <View className="small muted">{d.count}</View>
              <View
                className="bar"
                style={{
                  height: Math.max(1, (d.count / Math.max(1, ...daily.map((x) => x.count))) * 85),
                }}
              />
              <View className="bar-label">{d.label}</View>
            </View>
          ))}
        </View>
        <Buddy who="paper">多选题可以慢一点，把每个选项都过一遍。</Buddy>
      </>
    )
  }
  if (screen === 'wrongs') {
    const topics = ['全部主题', ...new Set(wrongs.map((w) => w.session.quiz.title))],
      topic = topics[topicFilter] || topics[0]
    const list = wrongs.filter(
      (w) =>
        w.status.mastered === !!wrongTab && (topic === topics[0] || w.session.quiz.title === topic),
    )
    body = (
      <>
        <Hero sub="不是没学会，是还差一次相遇。" who="paper">
          错过一次，{`\n`}
          <Text className="handline">再懂一次。</Text>
        </Hero>
        <Segments
          items={[`待复习 ${pending.length}`, `已掌握 ${wrongs.length - pending.length}`]}
          value={wrongTab}
          onChange={setWrongTab}
        />
        <Chips
          items={topics}
          value={topicFilter < topics.length ? topicFilter : 0}
          onChange={setTopicFilter}
        />
        {list.length
          ? list.map((w) => (
              <Row
                key={w.key}
                title={w.question.stem}
                sub={`${w.session.quiz.title} · ${typeName(w.question.type)} · ${when(w.session.started_at)}`}
                end={!w.status.mastered ? <Tag color="red">今天复习</Tag> : undefined}
                onClick={() => openWrong(w)}
                textLed
              />
            ))
          : empty(
              wrongTab ? '这里，还没有已掌握的旧题' : '暂时没有待复习错题',
              '每次弄懂一点，就是在前进。',
            )}
        <View className="review-note">答对后移入「已掌握」，{`\n`}历史答案仍会保留。</View>
      </>
    )
    footer = (
      <>
        <View className="footer-summary">
          <Text className="strong">{list.length}</Text> 道题，预计{' '}
          <Text className="strong">{Math.ceil(list.length / 2)}</Text> 分钟
        </View>
        <Btn disabled={!list.length} onClick={() => review(list)}>
          开始复习
        </Btn>
      </>
    )
  }
  if (screen === 'wrong' && wrong) {
    body = (
      <>
        <Tag color="blue">
          {typeName(wrong.question.type)} / {wrong.session.quiz.title}
        </Tag>
        <View className="question">{wrong.question.stem}</View>
        <View className="panel red answer-detail">
          <View>当时选择：{optionText(wrong.question, wrong.answer.selected)}</View>
          <View className="mt">正确答案：{optionText(wrong.question, wrong.question.answers)}</View>
        </View>
        <Section>容易漏掉的地方</Section>
        <View className="body-copy">{wrong.question.explanation}</View>
        <View className="inline-action mt" onClick={() => setExpanded(!expanded)}>
          {expanded ? '收起全部选项' : '查看全部选项与解释'}
        </View>
        {expanded &&
          wrong.question.options.map((o) => (
            <View key={o.id} className="answer-detail mt">
              {o.id}. {o.text}
            </View>
          ))}
        <Section>复习记录</Section>
        <View className="setting-row">
          <Text>首次作答</Text>
          <Text className="setting-value">{when(wrong.session.started_at)}</Text>
        </View>
        {wrong.status.reviews.map((r, i) => (
          <View className="setting-row" key={i}>
            <Text>{when(r.at)}</Text>
            <Tag color={r.correct ? 'green' : 'red'}>{r.correct ? '答对' : '待巩固'}</Tag>
          </View>
        ))}
        <View
          className="setting-row"
          onClick={() =>
            void api('/api/v1/wrongs', 'PUT', { key: wrong.key, mastered: !wrong.status.mastered }).then(() => refresh()).catch(e => setDialog({ title: '状态未保存', message: e.message }))
          }
        >
          <Text>{wrong.status.mastered ? '重新设为待复习' : '标记为已掌握'}</Text>
          <Icon name="refresh" />
        </View>
        <Buddy who="paper">多选题的坑，常常藏在“还有一个也对”。</Buddy>
      </>
    )
    footer = <Btn onClick={() => review([wrong])}>现在重温这一题</Btn>
  }
  if (screen === 'queue') {
    body = (
      <>
        <Title sub="用几分钟，把模糊的知识擦清楚。">
          今天，<Text className="handline">再遇见它们</Text>
        </Title>
        <WeeklyReview wrongs={wrongs} />
        <View className="comic-panel blue mt">
          <View className="row">
            <View>
              <View className="question" style={{ margin: 0 }}>
                {pending.length} 道题，慢慢来
              </View>
              <View className="small muted">
                预计 {Math.ceil(pending.length / 2)} 分钟 /{' '}
                {new Set(pending.map((w) => w.session.id)).size} 个主题
              </View>
            </View>
            <Icon name="refresh" />
          </View>
        </View>
        <Section>本次复习内容</Section>
        {pending.map((w) => (
          <Row
            key={w.key}
            title={w.question.stem}
            sub={w.session.quiz.title}
            onClick={() => openWrong(w)}
            textLed
          />
        ))}
        <Buddy who="paper">这次试着先解释给我听，再选答案。</Buddy>
        <View className="hint-note">复习不重复发放新学奖励。</View>
      </>
    )
    footer = (
      <Btn disabled={!pending.length} onClick={() => review(pending)}>
        开始旧识重温
      </Btn>
    )
  }
  if (screen === 'mine') body = <Mine profile={profile} go={go} future={future} />
  if (screen === 'settings')
    body = (
      <SettingsView
        go={go}
        future={future}
        exportRecords={exportRecords}
        notice={(kind) =>
          setDialog(
            kind === 'privacy'
              ? {
                  title: '隐私说明',
                  message: PRIVACY,
                }
              : {
                  title: '关于这个学习搭子',
                  message: TERMS,
                },
          )
        }
      />
    )
  if (screen === 'data')
    body = (
      <>
        <Title>管理你的学习数据</Title>
        <View className="hint-note">清理前可以先导出记录。学习历史、题库与已发放奖励会保留。</View>
        <Row title="导出全部学习记录" icon="download" onClick={exportRecords} />
        <Row
          title="清理本机缓存"
          sub="清空缓存和输入草稿，保留云端学习历史"
          icon="trash"
          onClick={() =>
            setDialog({
              title: '清理本机缓存？',
              message: '本机缓存与首页输入会清空，云端题库、作答和报告会保留。',
              confirm: () => dispatch({ type: 'CLEAR_CACHE' }),
            })
          }
        />
        <Row
          title="清空待复习队列"
          sub="将现有错题标为已掌握，保留历史答案"
          icon="refresh"
          onClick={() =>
            setDialog({
              title: '清空待复习队列？',
              message: '现有错题将移入「已掌握」，可在错题详情重新设为待复习。',
              confirm: () => { void api('/api/v1/wrongs/clear', 'POST').then(() => refresh()).catch(e => void Taro.showModal({ title: '清理暂未完成', content: e.message, showCancel: false })) },
            })
          }
        />
        <Row title="退出登录" icon="user" onClick={() => setDialog({ title: '退出当前账号？', message: '云端学习记录会保留，再次登录可以继续学习。', confirm: () => { void auth.logout().catch(e => void Taro.showModal({ title: '退出暂未完成', content: e.message, showCancel: false })) } })} />
        <Row title="注销账号" icon="trash" onClick={() => setDialog({ title: '注销并删除学习数据？', message: '资料、云端学习记录和奖励将删除，无法恢复。当天额度不会因重新注册而重置。', confirm: () => { void (async () => {
          const second = await Taro.showModal({ title: '最后确认注销', content: '确认删除全部账号数据，并重新验证微信身份？' })
          if (!second.confirm) return
          try { await api('/api/v1/me/delete', 'POST', { code: await wechatCode(), confirmation: '注销账号' }); Taro.removeStorageSync('levelup.account.v1.' + auth.user.id); clearCredentials() }
          catch (e) { void Taro.showModal({ title: '注销未完成', content: (e as Error).message, showCancel: false }) }
        })() } })} />
      </>
    )
  if (screen === 'error') {
    body = (
      <>
        <Stage who="paper" sticker="记录还在，慢慢来" />
        <Title sub={error.message}>
          {error.kind === 'quiz' ? (
            <>
              暂时没能<Text className="handline">生成关卡</Text>
            </>
          ) : (
            <>
              总结，再<Text className="handline">等一小会儿</Text>
            </>
          )}
        </Title>
        <View className="hint-note">
          {error.kind === 'quiz'
            ? '输入内容已保留，可以重试或回到首页修改。'
            : '题库与作答记录已完整保存，可在学习记录中重试报告。'}
        </View>
      </>
    )
    footer = (
      <>
        <Btn onClick={() => (error.kind === 'quiz' ? start() : record && reportFor(record))}>
          重新试一次
        </Btn>
        <Btn secondary onClick={() => root(error.kind === 'quiz' ? 'home' : 'history')}>
          {error.kind === 'quiz' ? '返回修改内容' : '先去学习记录'}
        </Btn>
      </>
    )
  }

  let status = 33
  if (process.env.TARO_ENV === 'weapp') {
    try {
      status = Taro.getWindowInfo().statusBarHeight || 20
    } catch {
      status = 20
    }
  }
  return (
    <View
      className={`app-shell ${refined ? 'footer-refined' : ''} ${screen === 'quiz' ? 'question-layout' : ''}`}
      data-id={id}
    >
      {process.env.TARO_ENV === 'h5' ? (
        <View className="status-bar">
          <Text>9:41</Text>
          <View className="status-icons">
            <Icon name="signal" />
            <Icon name="wifi" />
            <View className="battery">
              <View style={{ background: '#202a3d', height: '100%', width: '80%' }} />
            </View>
          </View>
        </View>
      ) : (
        <View className="status-bar native" style={{ height: status, minHeight: status }} />
      )}
      <View className="mini-bar">
        <View className="mini-title">
          {!['home', 'review', 'mine', 'welcome'].includes(screen) && (
            <View className="mini-back" onClick={back}>
              <Icon name="back" />
            </View>
          )}
          <Text className="mini-label">
            {screen === 'quiz' && active?.mode === 'review' ? '旧识重温' : labels[screen]}
          </Text>
        </View>
        {process.env.TARO_ENV === 'h5' && (
          <View className="wechat-capsule">
            <View className="capsule-divider" />
          </View>
        )}
      </View>
      <ScrollView
        scrollY
        className="phone-scroll"
        key={scrollKey}
        scrollTop={scrollPositions.current[scrollKey] || 0}
        onScroll={e => { scrollPositions.current[scrollKey] = e.detail.scrollTop }}
      >
        <View className="content">{cloudLoading && <View className="notice">正在同步云端学习记录…</View>}{cloudError && <View className="notice" onClick={() => void refresh().catch(() => {})}>{cloudError} 点击重试同步</View>}{body}</View>
      </ScrollView>
      {footer && <View className="phone-bottom">{footer}</View>}
      {['home', 'review', 'mine'].includes(screen) && (
        <View className="tabbar">
          {[
            ['home', '首页'],
            ['review', '复盘'],
            ['mine', '我的'],
          ].map(([key, label], i) => (
            <View
              key={key}
              className={`tab ${screen === key ? 'active' : ''}`}
              onClick={() => root(key as Screen)}
            >
              <Icon name={['home', 'book', 'user'][i]} />
              <Text>{label}</Text>
            </View>
          ))}
        </View>
      )}
      {paused && screen === 'quiz' && active && (
        <View className="sheet-overlay">
          <View className="sheet">
            <View className="sheet-handle" />
            <View className="sheet-title">
              先<Text className="handline">歇一下</Text>？
            </View>
            <View className="sheet-copy">
              本轮已完成 {active.answers.length} / {active.quiz.questions.length}{' '}
              题。保存后，下次可以接着学；未完成的关卡不会计为通关。
            </View>
            <Btn onClick={() => setPaused(false)}>继续答题</Btn>
            <Btn secondary onClick={() => root('home')}>
              保存进度并离开
            </Btn>
          </View>
        </View>
      )}
      {dialog && (
        <View className="global-dialog">
          <View className="dialog-card">
            <View className="dialog-title">{dialog.title}</View>
            <View className="dialog-copy">{dialog.message}</View>
            <Btn
              onClick={() => {
                dialog.confirm?.()
                setDialog(undefined)
              }}
            >
              {dialog.confirm ? '确认操作' : '知道了'}
            </Btn>
            {dialog.confirm && (
              <Btn secondary onClick={() => setDialog(undefined)}>
                先保留
              </Btn>
            )}
          </View>
        </View>
      )}
    </View>
  )
}
