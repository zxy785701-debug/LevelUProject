import React from 'react'
import { View, Text } from '@tarojs/components'
import { Wrong } from './domain'
import { Icon } from './components'
export function WeeklyReview({ wrongs }: { wrongs: Wrong[] }) {
  const now = new Date(),
    start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - ((now.getDay() + 6) % 7))
  const dates = new Set(
    wrongs.flatMap((w) => w.status.reviews.map((r) => new Date(r.at).toDateString())),
  )
  return (
    <View className="calendar-row">
      {['一', '二', '三', '四', '五', '六', '日'].map((label, i) => {
        const date = new Date(start)
        date.setDate(date.getDate() + i)
        const done = dates.has(date.toDateString()),
          today = date.toDateString() === now.toDateString()
        return (
          <View key={i} className={`calendar-day ${done ? 'done' : ''} ${today ? 'today' : ''}`}>
            <Text>{label}</Text>
            <View className="calendar-number">{done ? <Icon name="check" /> : date.getDate()}</View>
          </View>
        )
      })}
    </View>
  )
}
