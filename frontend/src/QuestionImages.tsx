import React, { useEffect, useState } from 'react'
import { Image, Switch, Text, View } from '@tarojs/components'
import { RequestScope } from './api'
import { getImageCapabilities } from './image-api'
import { imageAvailability, imageGenerationMessage } from './image-domain'
import type { ImageCapabilities } from './image-domain'
import type { Question, Quiz } from './domain'
import './question-images.scss'

export function useImageCapabilities(uid: string, refresh: number) {
  const [value, setValue] = useState<ImageCapabilities>()
  useEffect(() => {
    const request = new RequestScope()
    let live = true
    void getImageCapabilities(request).then(result => { if (live) setValue(result) }).catch(() => {
      if (live) setValue({ available: false, remaining: 0, daily_limit: 20, resolution: '512×512', reason_code: 'IMAGE_CAPABILITY_UNAVAILABLE' })
    })
    return () => { live = false; request.cancel() }
  }, [uid, refresh])
  return value
}

export function ImageChoice({ checked, onChange, capabilities }: {
  checked: boolean; onChange: (value: boolean) => void; capabilities?: ImageCapabilities
}) {
  const available = !!capabilities?.available && capabilities.remaining > 0
  return <View className="image-choice">
    <View className="setting-row image-setting">
      <View><Text className="strong">生成图片</Text><View className="small muted mt">为每道题配一张相关图片，辅助理解和记忆。</View></View>
      <Switch color="#336ae8" checked={checked} disabled={!available && !checked} ariaLabel="生成图片" onChange={e => onChange(e.detail.value)} />
    </View>
    <View className="small muted image-choice-note" ariaRole="status">{imageAvailability(capabilities)}</View>
    {checked && <View className="small muted image-choice-note">题目描述会发送至生图服务，生成的配图通过公开图片链接展示。配图可能有误；失败时仍可文字学习。已发出的请求计入每日额度。</View>}
  </View>
}

export function QuestionIllustration({ question }: { question: Question }) {
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading')
  useEffect(() => setState('loading'), [question.id, question.image_url])
  if (!question.image_url) return null
  return <View className={`question-illustration ${state === 'failed' ? 'image-failed' : ''}`}>
    {state === 'failed' ? <View className="small muted image-load-message" ariaRole="status">配图暂时无法加载，可以继续答题。</View> : <View className="question-image-frame">
      <Image className="question-image" src={question.image_url} mode="aspectFit" lazyLoad ariaLabel="本题 AI 辅助配图"
        onLoad={() => setState('ready')} onError={() => setState('failed')} />
      {state === 'loading' && <View className="image-loading small muted" ariaRole="status">配图加载中…</View>}
    </View>}
    {state !== 'failed' && <View className="small muted image-caption">AI 辅助配图</View>}
  </View>
}

export function ImageGenerationNotice({ quiz }: { quiz: Quiz }) {
  const message = imageGenerationMessage(quiz.image_generation)
  return message ? <View className="image-generation-notice small muted" ariaRole="status">{message}</View> : null
}
