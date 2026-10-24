import React, { useEffect, useState } from 'react'
import { Progress, View } from '@tarojs/components'
import { stageLabel } from './grounding-domain'

export const stageProgress = (stage?: string | null) => ({
  planning: 10, retrieving: 20, searching: 25, extracting: 40,
  summarizing: 70, generating: 65, reviewing: 90, generating_images: 95, ready: 100, succeeded: 100,
})[stage || ''] || 5

export function GenerationProgress({ stage }: { stage?: string | null }) {
  const [percent, setPercent] = useState(stageProgress(stage))
  useEffect(() => { if (stage !== 'waiting_rate_limit') setPercent(previous => Math.max(previous, stageProgress(stage))) }, [stage])
  return <View className="generation-progress" ariaRole="status">
    <Progress percent={percent} strokeWidth={8} activeColor="#336ae8" backgroundColor="#e8edf5" />
    <View className="small muted mt">{stageLabel(stage)} · 阶段进度</View>
  </View>
}
