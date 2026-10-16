import React, { useEffect, useRef, useState } from 'react'
import Taro from '@tarojs/taro'
import { View, Text, Image, Canvas, Checkbox, Picker } from '@tarojs/components'
import { Btn, Buddy, Chips, Hero, Icon, Mastery, Row, Section, Segments, Stage, Stat, Tag, Title } from './components'
import { Trend } from './Trend'
import { surface } from './platform'
import { ApiError, operationKey } from './api'
import { getAnalytics, getKnowledgeMap, getPeriodReports, createPeriodReport, exportPeriodReport } from './features-api'
import { Analytics, KnowledgeMap, KnowledgePoint, PeriodReport, ReportSection, periodDates, reportHeading } from './features-domain'
import { typeName } from './domain'
import { GroundingNotice } from './GroundingNotice'
import { SourceReader } from './MaterialFlow'

export type AnalysisScreen = 'map' | 'analytics' | 'periodSetup' | 'periodReport'
function MapLines({ count }: { count: number }) {
  const [src, setSrc] = useState('')
  useEffect(() => {
    let live = true
    void (async () => {
      const { canvas, ctx } = await surface('map-lines-canvas', 330, 210)
      ctx.clearRect(0, 0, 330, 210); ctx.strokeStyle = '#b6c9ee'; ctx.lineWidth = 2
      for (const [x, y] of [[55,35],[285,35],[65,175],[280,175]].slice(0, count)) { ctx.beginPath(); ctx.moveTo(165,105); ctx.lineTo(x,y); ctx.stroke() }
      const path = process.env.TARO_ENV === 'h5' ? canvas.toDataURL('image/png') : (await Taro.canvasToTempFilePath({ canvas, width: 660, height: 420, destWidth: 660, destHeight: 420 } as any)).tempFilePath
      if (live) setSrc(path)
    })().catch(() => {})
    return () => { live = false }
  }, [count])
  return <>{src && <Image className="map-lines" src={src} mode="scaleToFill" />}<Canvas id="map-lines-canvas" canvasId="map-lines-canvas" type="2d" className="canvas-hidden" /></>
}
const stateName = { mastered: '已掌握', weak: '待巩固', explore: '可继续探索' }
const stateColor = { mastered: 'green', weak: 'red', explore: 'blue' }
function StatsChart({ data }: { data: Analytics }) {
  return <><Section>正确率趋势</Section>{data.totals.total ? <Trend points={data.trend.map(v => ({ label: v.date.slice(5).replace('-', '/'), accuracy: v.accuracy }))} /> : <View className="hint-note">完成第一关后，这里会显示真实趋势。</View>}<Section>题型表现</Section>{(['single','multi','judge'] as const).map(type => { const item = data.types.find(v => v.type === type); return <Mastery key={type} label={`${typeName(type)} / ${item?.total || 0} 题`} value={item?.accuracy || 0} color={type === 'multi' ? 'yellow' : 'green'} /> })}</>
}

export function usePersonalAnalysis({ screen, navigate, onPoint, onReview }: { screen: string; navigate: (screen: AnalysisScreen) => void; onPoint: (point: KnowledgePoint, topic: string) => void; onReview: () => void }) {
  const [range, setRange] = useState(0), [stats, setStats] = useState<Analytics>(), [tree, setTree] = useState<KnowledgeMap>(), [topicIndex, setTopicIndex] = useState(0)
  const [periodRange, setPeriodRange] = useState(0), [dates, setDates] = useState(() => periodDates(7)), [sections, setSections] = useState<ReportSection[]>(['overview', 'performance', 'advice'])
  const [reports, setReports] = useState<PeriodReport[]>([]), [report, setReport] = useState<PeriodReport>(), [preview, setPreview] = useState<Analytics>()
  const [sourceAttempt, setSourceAttempt] = useState('')
  const [error, setError] = useState(''), [loading, setLoading] = useState(false), [generating, setGenerating] = useState(false), [saving, setSaving] = useState(false), [reload, setReload] = useState(0)
  const key = useRef(''), working = useRef(false), screenRef = useRef(screen), alive = useRef(true)
  screenRef.current = screen
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => {
    if (!['map','analytics','periodSetup'].includes(screen)) return
    let live = true; setError(''); setLoading(true)
    const work = screen === 'map' ? getKnowledgeMap().then(v => { if (live) setTree(v) }) : screen === 'analytics' ? getAnalytics(['7','30','all'][range]).then(v => { if (live) setStats(v) }) : getAnalytics('custom', dates.start, dates.end).then(v => { if (live) setPreview(v) })
    if (screen === 'periodSetup') void getPeriodReports().then(v => { if (live) setReports(v) }).catch(() => {})
    void work.catch(e => { if (live) setError(e.message) }).finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [screen, range, dates.start, dates.end, reload])
  async function generate() {
    if (working.current || !sections.length) return
    working.current = true; setGenerating(true); setError('')
    try {
      const result = await createPeriodReport('custom', dates.start, dates.end, sections, key.current || (key.current = operationKey()))
      key.current = ''
      if (alive.current) { setReport(result); if (screenRef.current === 'periodSetup') navigate('periodReport') }
    } catch (e) { if (alive.current) { if (!(e instanceof ApiError) || !['NETWORK_ERROR','AI_BUSY'].includes(e.code)) key.current = ''; setError((e as Error).message) } }
    finally { working.current = false; if (alive.current) setGenerating(false) }
  }
  let body: React.ReactNode = null, footer: React.ReactNode = null
  if (screen === 'map') {
    const topic = tree?.topics[topicIndex] || tree?.topics[0]
    body = <><Title sub="把零散知识连起来，看看下一步走哪里。">原来，已经学了这么多</Title>{topic ? <><Chips items={tree!.topics.map(t => t.name)} value={topicIndex < tree!.topics.length ? topicIndex : 0} onChange={setTopicIndex} /><View className="knowledge-map"><MapLines count={topic.points.length} /><View className="map-node root">{topic.name}</View>{topic.points.slice(0,4).map((p, i) => <View ariaRole="button" ariaLabel={`${p.name}，${stateName[p.status]}`} key={p.id} className={`map-node ${'abcd'[i]} state-${p.status}`} onClick={() => onPoint(p, topic.name)}>{p.name}{p.status === 'mastered' ? ' ✓' : ''}</View>)}</View><View className="tags"><Tag color="green">✓ 已掌握</Tag><Tag color="red">待巩固</Tag><Tag color="blue">可继续探索</Tag></View><Section>值得再看一眼</Section>{topic.points.map(p => <Row key={p.id} title={p.name} sub={`${p.correct} / ${p.total} 道不同题 / ${p.accuracy}%`} icon={p.status === 'weak' ? 'refresh' : 'spark'} end={<Tag color={stateColor[p.status]}>{stateName[p.status]}</Tag>} color={stateColor[p.status]} onClick={() => onPoint(p, topic.name)} />)}<View className="small muted mt">{tree?.rule}</View></> : !loading && !error ? <><Stage who="paper" /><Title sub="完成一关后，真实知识点会在这里连起来。">知识地图，等你点亮</Title></> : null}</>
  }
  if (screen === 'analytics') {
    const value = stats?.totals, daily = stats?.trend.slice(-7) || []
    body = <><Title>看见自己的进步</Title><Segments items={['近 7 天','近 30 天','全部']} value={range} onChange={setRange} /><View className="row"><Tag>云端新学记录</Tag><Text className="text-btn" onClick={() => navigate('periodSetup')}>生成报告<Icon name="chevron" /></Text></View>{stats && !loading && <><Stat items={[[value!.accuracy === null ? '—' : `${value!.accuracy}%`, '平均正确率'], [value!.total, '完成题数'], [`${Math.round(value!.duration_ms/60000)} 分钟`, '学习用时']]} /><StatsChart data={stats} /><Section>最近一周学习量 · 题</Section><View className="bar-grid">{daily.map(d => <View className="bar-col" key={d.date}><View className="small muted">{d.total}</View><View className="bar" style={{ height: Math.max(1,d.total/Math.max(1,...daily.map(v=>v.total))*85) }} /><View className="bar-label">{d.date.slice(5)}</View></View>)}</View><Buddy who="paper">按自己的节奏，多给薄弱知识一次练习。</Buddy></>}</>
  }
  if (screen === 'periodSetup') {
    body = <><Hero sub="看看这段时间，哪些知识真正留下了。">整理一段{`\n`}学习的旅程</Hero><Section>报告时间范围</Section><Chips items={['最近 7 天','最近 30 天','自定义']} value={periodRange} onChange={i => { setPeriodRange(i); key.current = ''; if (i < 2) setDates(periodDates(i === 0 ? 7 : 30)) }} /><View className="date-fields mt">{(['start','end'] as const).map(field => <View key={field}><Text className="small">{field === 'start' ? '开始日期' : '结束日期'}</Text><Picker mode="date" value={dates[field]} end={periodDates(1).end} onChange={e => { setDates(v => ({ ...v, [field]: e.detail.value })); setPeriodRange(2); key.current = '' }}><View className="input" ariaLabel={field === 'start' ? '开始日期' : '结束日期'}>{dates[field]}</View></Picker></View>)}</View><Section>报告包含</Section><View className="stack">{(['overview','performance','advice'] as const).map((s, i) => <View className="check-label" key={s}><Checkbox value={s} color="#336ae8" checked={sections.includes(s)} disabled={generating} onClick={() => { setSections(old => old.includes(s) ? old.filter(v => v !== s) : [...old,s]); key.current = '' }} />{['学习主题与时间','正确率趋势与题型表现','薄弱知识和下阶段建议'][i]}</View>)}</View><View className="panel blue mt"><View className="strong small">这段时间里</View><View className="small muted mt">{loading ? '正在读取已有学习记录…' : preview ? `学习 ${preview.totals.topics} 个主题，完成 ${preview.totals.total} 道题。报告根据已有学习记录生成。` : '请选择有效的学习时段。'}</View></View>{generating && <View className="hint-note">正在根据真实作答整理报告，离开后可在这里查看生成结果。</View>}{reports.length > 0 && <><Section>已生成的报告</Section>{reports.map(r => <Row key={r.id} title={`${r.snapshot.current.range.start} 至 ${r.snapshot.current.range.end}`} sub={r.status === 'succeeded' ? '已完成 / 点击查看' : r.status === 'running' ? '正在生成 / 稍后刷新查看' : '未完成 / 可选择相同时段重试'} icon="file" onClick={r.status === 'succeeded' ? () => { setReport(r); navigate('periodReport') } : () => setReload(v => v+1)} />)}</>}</>
    footer = <Btn disabled={generating || loading || !!error || !sections.length || !preview?.totals.total} onClick={() => void generate()}>{generating ? '正在整理这段学习…' : '生成这段时间的报告'}</Btn>
  }
  if (screen === 'periodReport' && report?.content) {
    const snap = report.snapshot, value = snap.current.totals, points = new Map(snap.knowledge.topics.flatMap(t=>t.points).map(p => [p.id,p]))
    body = <><Tag color="blue">周期学习报告</Tag><Title>{reportHeading(snap.previous.totals.accuracy,value.accuracy)}</Title><View className="small muted mt">{snap.current.range.start} – {snap.current.range.end}</View>{snap.sections.includes('overview') && <Stat items={[[value.topics,'学习主题'],[value.total,'完成题数'],[`${Math.round(value.duration_ms/60000)} 分钟`,'学习时间']]} />}{report.content.summary.map((line,i) => <View className="body-copy mt" key={i}>{line}</View>)}{snap.sections.includes('performance') && <><Section>从答题里看进步</Section><Trend points={snap.current.trend.map(v=>({ label:v.date.slice(5),accuracy:v.accuracy }))} /><View className="small muted mt">本期正确率 {value.accuracy}%；{snap.previous.totals.accuracy === null ? '前期没有可比较记录。' : `前期 ${snap.previous.totals.accuracy}%。`}</View></>}{snap.sections.includes('advice') && <>{[...points.values()].map(p => <View key={p.id} className={`panel ${p.status === 'mastered' ? 'green' : 'blue'} mt`}><View className="strong">{p.name} / {stateName[p.status]}</View><View className="small muted mt">{p.correct} / {p.total} 道不同题，正确率 {p.accuracy}%。{p.total < 3 ? '样本还少，需要继续观察。' : '掌握度根据有效作答估计。'}</View></View>)}{report.content.findings.map((v,i) => <View className="body-copy mt" key={i}>{points.get(v.point_id)?.name}：{v.analysis}</View>)}<Section>下一段，试着这样学</Section><View className="takeaway">{report.content.suggestions.map((v,i) => <View className="takeaway-line" key={i}>{points.get(v.point_id)?.name}：{v.action}</View>)}{!report.content.suggestions.length && <View className="takeaway-line">从待复习的题目开始，用自己的话解释知识点，再检验理解。</View>}</View><Row title="从待复习开始" sub="把薄弱知识再串起来" icon="refresh" onClick={onReview} /></>}</>
    body = <>{body}<Section>学习依据与核实状态</Section>{snap.provenance?.length ? snap.provenance.map(item => <View key={item.attempt_id} className="panel mt"><View className="strong">{item.title}</View><GroundingNotice value={item.verification} scope={item.learning_scope} />{!!item.source?.segments.length && <Btn secondary onClick={() => setSourceAttempt(sourceAttempt === item.attempt_id ? '' : item.attempt_id)}>{sourceAttempt === item.attempt_id ? '收起参考资料' : '查看参考资料'}</Btn>}{sourceAttempt === item.attempt_id && item.source && <SourceReader title={item.source.title} segments={item.source.segments} grounding={item.verification} />}</View>) : <GroundingNotice />}</>
    footer = <Btn disabled={saving} onClick={() => { setSaving(true); setError(''); void exportPeriodReport(report.id).catch(e=>setError(e.message)).finally(()=>setSaving(false)) }}><Icon name="download-white" />{saving ? '正在保存…' : '保存文字报告'}</Btn>
  }
  return { body: <>{body}{loading && screen !== 'periodReport' && <View className="notice">正在读取云端学习数据…</View>}{error && <View className="field-error" onClick={() => { setError(''); setReload(v=>v+1) }}>{error} 点击重新读取</View>}</>, footer }
}
