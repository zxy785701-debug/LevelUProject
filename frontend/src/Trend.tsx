import React, { useEffect, useState } from 'react'
import Taro from '@tarojs/taro'
import { View, Canvas, Image } from '@tarojs/components'
import { surface } from './platform'
export function Trend({ points }: { points: { label: string; accuracy: number | null }[] }) {
  const [src, setSrc] = useState(''),
    signature = JSON.stringify(points)
  useEffect(() => {
    let live = true
    ;(async () => {
      const { canvas, ctx } = await surface('trend-canvas', 300, 142)
      ctx.clearRect(0, 0, 300, 142)
      ctx.strokeStyle = '#e1e6ef'
      ctx.lineWidth = 1
      for (const y of [12, 62, 112]) {
        ctx.beginPath()
        ctx.moveTo(29, y)
        ctx.lineTo(290, y)
        ctx.stroke()
      }
      ctx.fillStyle = '#69758a'
      ctx.font = '9px sans-serif'
      ctx.fillText('100%', 0, 16)
      ctx.fillText('50%', 8, 66)
      ctx.fillText('0%', 15, 116)
      ctx.fillText(points[0]?.label || '', 29, 134)
      ctx.textAlign = 'right'
      ctx.fillText(points[points.length - 1]?.label || '', 290, 134)
      ctx.textAlign = 'left'
      ctx.strokeStyle = '#336ae8'
      ctx.lineWidth = 2.5
      let last: { x: number; y: number } | null = null
      points.forEach((p, i) => {
        if (p.accuracy === null) {
          last = null
          return
        }
        const x = points.length <= 1 ? 159 : 30 + (258 * i) / (points.length - 1),
          y = 112 - p.accuracy
        if (last) {
          ctx.beginPath()
          ctx.moveTo(last.x, last.y)
          ctx.lineTo(x, y)
          ctx.stroke()
        }
        ctx.fillStyle = '#336ae8'
        ctx.beginPath()
        ctx.arc(x, y, 3, 0, Math.PI * 2)
        ctx.fill()
        last = { x, y }
      })
      const path =
        process.env.TARO_ENV === 'h5'
          ? canvas.toDataURL('image/png')
          : (
              await Taro.canvasToTempFilePath({
                canvas,
                width: 600,
                height: 284,
                destWidth: 600,
                destHeight: 284,
              } as any)
            ).tempFilePath
      if (live) setSrc(path)
    })().catch(() => {})
    return () => {
      live = false
    }
  }, [signature])
  return (
    <View>
      {src && <Image src={src} className="chart-image" mode="aspectFit" />}
      <Canvas type="2d" id="trend-canvas" canvasId="trend-canvas" className="canvas-hidden" />
    </View>
  )
}
