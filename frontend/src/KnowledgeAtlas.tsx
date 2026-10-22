import React, { useEffect, useMemo, useRef, useState } from 'react'
import Taro from '@tarojs/taro'
import { Button, Input, Text, View, ITouchEvent } from '@tarojs/components'
import { Row, Tag } from './components'
import type { KnowledgeMap, KnowledgePoint } from './features-domain'
import { Camera, focusCamera, NODE_HEIGHT, NODE_WIDTH, searchTopics, topicLayout, visibleTopics } from './knowledge-map'

const states = { mastered: '已掌握', weak: '待巩固', explore: '可继续探索' }
const colors = { mastered: 'green', weak: 'red', explore: 'blue' }
const PAGE_SIZE = 6
const DEFAULT_SCALE = .6

export function KnowledgeAtlas({ tree, onPoint }: { tree: KnowledgeMap; onPoint: (point: KnowledgePoint, topic: string) => void }) {
  const layout = useMemo(() => topicLayout(tree.topics), [tree.topics])
  const topics = useMemo(() => new Map(tree.topics.map(t => [t.id, t])), [tree.topics])
  const [size, setSize] = useState({ width: 350, height: 360 })
  const [query, setQuery] = useState(''), [resultPage, setResultPage] = useState(0)
  const [selected, setSelected] = useState(''), [pointPage, setPointPage] = useState(0)
  const initial = focusCamera({ x: layout.center, y: layout.center }, DEFAULT_SCALE, size.width, size.height)
  const [camera, setCamera] = useState<Camera>(initial)
  const current = useRef(camera), timer = useRef<ReturnType<typeof setTimeout>>()
  const viewportSize = useRef(size)
  const bounds = useRef({ left: 0, top: 0 })
  const gesture = useRef({ x: 0, y: 0, distance: 0, fingers: 0, camera: initial, moved: false })
  const matches = useMemo(() => searchTopics(tree.topics, query), [tree.topics, query])
  const topic = topics.get(selected)
  const nodes = tree.topics.length > 100 ? visibleTopics(layout.nodes, camera, size.width, size.height) : layout.nodes

  function move(next: Camera) {
    if (timer.current) { clearTimeout(timer.current); timer.current = undefined }
    current.current = next; setCamera(next)
  }
  function locate(id: string) {
    const node = layout.nodes.find(n => n.id === id)
    if (!node) return
    setSelected(id); setPointPage(0); setQuery(''); setResultPage(0)
    move(focusCamera(node, 1, size.width, size.height))
  }
  function update(next: Camera) {
    current.current = next
    if (!timer.current) timer.current = setTimeout(() => { setCamera(current.current); timer.current = undefined }, 16)
  }
  function begin(event: ITouchEvent, preserve = false) {
    const touches = event.touches, a = touches[0], b = touches[1] || a
    if (!a) return
    gesture.current = { x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2,
      distance: touches.length > 1 ? Math.hypot(b.clientX - a.clientX, b.clientY - a.clientY) : 0,
      fingers: Math.min(2, touches.length), camera: current.current, moved: preserve || touches.length > 1 }
  }
  function drag(event: ITouchEvent) {
    event.preventDefault?.()
    const touches = event.touches, a = touches[0], b = touches[1] || a, start = gesture.current
    if (!a) return
    if (start.fingers !== Math.min(2, touches.length)) { begin(event, true); return }
    const x = (a.clientX + b.clientX) / 2, y = (a.clientY + b.clientY) / 2
    if (Math.hypot(x - start.x, y - start.y) > 8 || touches.length > 1) start.moved = true
    const scale = start.distance ? Math.max(.5, Math.min(2, start.camera.scale * Math.hypot(b.clientX - a.clientX, b.clientY - a.clientY) / start.distance)) : start.camera.scale
    const ratio = scale / start.camera.scale
    const next = { x: x - bounds.current.left - (start.x - bounds.current.left - start.camera.x) * ratio,
      y: y - bounds.current.top - (start.y - bounds.current.top - start.camera.y) * ratio, scale }
    next.x = Math.max(Math.min(0, size.width - layout.size * scale), Math.min(0, next.x))
    next.y = Math.max(Math.min(0, size.height - layout.size * scale), Math.min(0, next.y))
    update(next)
  }
  function zoom(amount: number) {
    const old = current.current, scale = Math.max(.5, Math.min(2, old.scale + amount))
    const center = { x: (size.width / 2 - old.x) / old.scale, y: (size.height / 2 - old.y) / old.scale }
    move(focusCamera(center, scale, size.width, size.height))
  }
  useEffect(() => {
    let live = true
    move(focusCamera({ x: layout.center, y: layout.center }, DEFAULT_SCALE, viewportSize.current.width, viewportSize.current.height))
    const measure = () => Taro.nextTick(() => {
      Taro.createSelectorQuery().select('#topic-map-viewport').boundingClientRect(rect => {
        if (!live || !rect || Array.isArray(rect)) return
        const nextSize = { width: rect.width, height: rect.height }
        bounds.current = { left: rect.left, top: rect.top }
        const old = viewportSize.current, view = current.current
        const center = { x: (old.width / 2 - view.x) / view.scale, y: (old.height / 2 - view.y) / view.scale }
        viewportSize.current = nextSize
        setSize(nextSize)
        move(focusCamera(center, view.scale, nextSize.width, nextSize.height))
      }).exec()
    })
    measure(); Taro.onWindowResize(measure)
    return () => { live = false; Taro.offWindowResize(measure); if (timer.current) clearTimeout(timer.current) }
  }, [layout])

  return <View className="topic-atlas">
    <View className="atlas-summary"><Text className="strong">已连接 {tree.topics.length} 个学习主题</Text><Text className="small muted">点击主题，展开知识点</Text></View>
    <View className="atlas-search"><Input ariaLabel="搜索学习主题或知识点" placeholder="搜索主题或知识点，定位到地图" value={query} onInput={e => { setQuery(e.detail.value); setResultPage(0) }} />{!!query && <Button ariaLabel="清除搜索" onClick={() => setQuery('')}>清除</Button>}</View>
    {!!query.trim() && <View className="atlas-search-results">
      <View className="small muted">{matches.length ? `找到 ${matches.length} 个主题` : '没有找到相关主题，换个关键词试试。'}</View>
      {matches.slice(resultPage * PAGE_SIZE, (resultPage + 1) * PAGE_SIZE).map(t => <Button className="atlas-search-result" key={t.id} onClick={() => locate(t.id)}>{t.name}<Text>定位 ›</Text></Button>)}
      {matches.length > PAGE_SIZE && <View className="atlas-pagination"><Button disabled={!resultPage} onClick={() => setResultPage(p => p - 1)}>上一页</Button><Text>{resultPage + 1} / {Math.ceil(matches.length / PAGE_SIZE)}</Text><Button disabled={(resultPage + 1) * PAGE_SIZE >= matches.length} onClick={() => setResultPage(p => p + 1)}>下一页</Button></View>}
    </View>}
    <View id="topic-map-viewport" className="knowledge-map atlas-viewport" style={{ height: '360px' }} catchMove
      onTouchStart={e => {
        // The page may have scrolled since initial measurement.
        Taro.createSelectorQuery().select('#topic-map-viewport').boundingClientRect(rect => { if (rect && !Array.isArray(rect)) bounds.current = { left: rect.left, top: rect.top } }).exec()
        begin(e as ITouchEvent)
      }} onTouchMove={e => drag(e as ITouchEvent)} onTouchEnd={e => { if ((e as ITouchEvent).touches.length) begin(e as ITouchEvent, true) }} onTouchCancel={() => { gesture.current.moved = true }}>
        <View className="atlas-world" style={{ width: `${layout.size}px`, height: `${layout.size}px`, transform: `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})` }}>
          {nodes.map(node => <View key={'edge-' + node.id} className="atlas-edge" style={{ left: `${layout.center}px`, top: `${layout.center}px`, width: `${Math.hypot(node.x - layout.center, node.y - layout.center)}px`, transform: `rotate(${Math.atan2(node.y - layout.center, node.x - layout.center)}rad)` }} />)}
          <View className="atlas-hub" style={{ left: `${layout.center - 55}px`, top: `${layout.center - 35}px` }}><Text style={{ fontSize: `${12 / camera.scale}px` }}>我的知识</Text><Text style={{ fontSize: `${9 / camera.scale}px` }}>{tree.topics.length} 个主题</Text></View>
          {nodes.map(node => {
            const value = topics.get(node.id)!, weak = value.points.filter(p => p.status === 'weak').length
            return <View key={node.id} ariaRole="button" ariaLabel={`查看主题：${value.name}`} className={`atlas-node ${selected === node.id ? 'selected' : ''}`} style={{ left: `${node.x - NODE_WIDTH / 2}px`, top: `${node.y - NODE_HEIGHT / 2}px`, width: `${NODE_WIDTH}px`, height: `${NODE_HEIGHT}px` }} onClick={() => { if (!gesture.current.moved) { setSelected(node.id); setPointPage(0) } }}>
              <View className="atlas-node-title" style={{ fontSize: `${13 / camera.scale}px` }}>{value.name}</View>
              {camera.scale >= .7 && <Text className={`atlas-node-meta ${weak ? 'weak' : ''}`} style={{ fontSize: `${10 / camera.scale}px` }}>{weak ? `${weak} 个待巩固` : `${value.points.length} 个知识点`}</Text>}
            </View>
          })}
        </View>
      <View className="atlas-gesture-hint">拖动浏览 · 双指缩放</View>
    </View>
    <View className="atlas-tools">
      <Button ariaLabel="缩小知识地图" disabled={camera.scale <= .5} onClick={() => zoom(-.25)}>−</Button><Text className="small muted">{Math.round(camera.scale * 100)}%</Text><Button ariaLabel="放大知识地图" disabled={camera.scale >= 2} onClick={() => zoom(.25)}>＋</Button>
      <Button className="atlas-reset" onClick={() => { setSelected(''); move(focusCamera({ x: layout.center, y: layout.center }, DEFAULT_SCALE, size.width, size.height)) }}>回到中心</Button>
    </View>
    <View className="atlas-browse"><Button onClick={() => { const i = tree.topics.findIndex(t => t.id === selected); locate(tree.topics[i < 0 ? tree.topics.length - 1 : (i - 1 + tree.topics.length) % tree.topics.length].id) }}>上个主题</Button><Text className="small muted">{selected ? `${tree.topics.findIndex(t => t.id === selected) + 1} / ${tree.topics.length}` : '逐个浏览主题'}</Text><Button onClick={() => { const i = tree.topics.findIndex(t => t.id === selected); locate(tree.topics[(i + 1) % tree.topics.length].id) }}>下个主题</Button></View>
    <View className="small muted atlas-explanation">连线表示这些主题属于你的学习地图。</View>
    {topic && <View className="atlas-detail">
      <View className="atlas-detail-heading"><View className="strong">{topic.name}</View><Button ariaLabel="收起主题知识点" onClick={() => setSelected('')}>收起</Button></View>
      <View className="small muted">{topic.points.length} 个知识点 · 选择一个查看或练习</View>
      {topic.points.slice(pointPage * PAGE_SIZE, (pointPage + 1) * PAGE_SIZE).map(p => <Row key={p.id} title={p.name} sub={`${p.correct} / ${p.total} 道不同题 · ${p.accuracy}%`} icon={p.status === 'weak' ? 'refresh' : 'spark'} color={colors[p.status]} end={<Tag color={colors[p.status]}>{states[p.status]}</Tag>} onClick={() => onPoint(p, topic.name)} />)}
      {topic.points.length > PAGE_SIZE && <View className="atlas-pagination"><Button disabled={!pointPage} onClick={() => setPointPage(p => p - 1)}>上一页</Button><Text>{pointPage + 1} / {Math.ceil(topic.points.length / PAGE_SIZE)}</Text><Button disabled={(pointPage + 1) * PAGE_SIZE >= topic.points.length} onClick={() => setPointPage(p => p + 1)}>下一页</Button></View>}
      <View className="small muted mt">{tree.rule}</View>
    </View>}
  </View>
}
