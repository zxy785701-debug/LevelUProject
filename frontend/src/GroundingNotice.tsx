import React from 'react'
import { View } from '@tarojs/components'
import { Tag } from './components'
import { Grounding, Verification, LearningScope, groundingLabel } from './grounding-domain'
export function sourceDate(value?: string | null) {
  if (!value || !Number.isFinite(Date.parse(value))) return '未知日期'
  return value.slice(0, 10)
}
export function GroundingNotice({ value, scope }: { value?: Grounding | Verification | null; scope?: LearningScope | null }) {
  return <View className="grounding-notice mt"><Tag color={value?.status === 'unverified' || !value || value.status === 'unknown' ? 'yellow' : 'blue'}>{groundingLabel(value)}</Tag>{scope && <View className="small muted mt">学习范围：{scope.domain} · {scope.focus}</View>}{value?.status === 'unverified' && <View className="small muted mt">资料获取或支持不足，请结合可靠来源核对答案与讲解。</View>}{!value && <View className="small muted mt">此历史题库未记录核实状态。</View>}</View>
}
