import type { KnowledgeMap } from './features-domain'

export const NODE_WIDTH = 160, NODE_HEIGHT = 88
export interface MapNode { id: string; x: number; y: number }
export interface Camera { x: number; y: number; scale: number }

// Stable concentric rings keep topics apart without implying prerequisite links.
export function topicLayout(topics: KnowledgeMap['topics']) {
  const positions: MapNode[] = []
  const ordered = [...topics].sort((a, b) => a.id.localeCompare(b.id))
  let index = 0, radius = 0
  while (index < ordered.length) {
    radius += 220
    const capacity = Math.floor(2 * Math.PI * radius / 200)
    const count = Math.min(capacity, ordered.length - index)
    for (let i = 0; i < count; i++) {
      const angle = -Math.PI / 2 + i * 2 * Math.PI / count
      positions.push({ id: ordered[index++].id, x: Math.cos(angle) * radius, y: Math.sin(angle) * radius })
    }
  }
  const size = Math.max(640, (radius + 180) * 2), center = size / 2
  return { size, center, nodes: positions.map(p => ({ ...p, x: p.x + center, y: p.y + center })) }
}

export function focusCamera(node: { x: number; y: number }, scale: number, width: number, height: number): Camera {
  return { x: width / 2 - node.x * scale, y: height / 2 - node.y * scale, scale }
}

export function visibleTopics(nodes: MapNode[], camera: Camera, width: number, height: number) {
  const padding = 220 * camera.scale
  return nodes.filter(node => {
    const x = camera.x + node.x * camera.scale, y = camera.y + node.y * camera.scale
    return x > -padding && x < width + padding && y > -padding && y < height + padding
  })
}

export function searchTopics(topics: KnowledgeMap['topics'], query: string) {
  const term = query.trim().toLocaleLowerCase()
  return term ? topics.filter(t => t.name.toLocaleLowerCase().includes(term) || t.points.some(p => p.name.toLocaleLowerCase().includes(term))) : []
}
