import { describe, expect, it } from 'vitest'
import { focusCamera, NODE_HEIGHT, NODE_WIDTH, searchTopics, topicLayout, visibleTopics } from '../src/knowledge-map'

const topics = (n: number) => Array.from({ length: n }, (_, i) => ({ id: String(i).padStart(4, '0'), name: `学习主题 ${i}`, points: [] }))
describe('统一知识地图', () => {
  it('全部主题在同一个布局中，连线端点唯一，顺序不影响布局', () => {
    const all = topics(200), layout = topicLayout(all)
    expect(layout.nodes).toHaveLength(200)
    expect(new Set(layout.nodes.map(n => n.id)).size).toBe(200)
    expect(topicLayout([...all].reverse())).toEqual(layout)
    for (const a of layout.nodes) for (const b of layout.nodes) {
      if (a.id !== b.id) expect(Math.abs(a.x - b.x) >= NODE_WIDTH || Math.abs(a.y - b.y) >= NODE_HEIGHT).toBe(true)
    }
  })
  it('大量主题仅渲染可见区域，搜索可定位最外层主题', () => {
    const all = topics(1000), layout = topicLayout(all), target = layout.nodes[999]
    const camera = focusCamera(target, 1, 288, 360)
    expect(camera.x + target.x).toBe(144)
    expect(camera.y + target.y).toBe(180)
    const visible = visibleTopics(layout.nodes, camera, 288, 360)
    expect(visible).toContain(target)
    expect(visible.length).toBeLessThan(40)
    expect(searchTopics(all, '主题 999')).toEqual([all[999]])
  })
  it('搜索匹配知识点，空查询不铺开主题列表', () => {
    const all = [{ id: 't', name: 'FastAPI', points: [{ id: 'p', name: '请求验证' }] }] as any
    expect(searchTopics(all, '验证')).toEqual(all)
    expect(searchTopics(all, ' FASTapi ')).toEqual(all)
    expect(searchTopics(all, '')).toEqual([])
    expect(searchTopics(all, '不存在')).toEqual([])
  })
})
