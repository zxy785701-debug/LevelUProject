import React from 'react'
import { View, Text } from '@tarojs/components'
import { Icon, Title, Stat, Row } from './components'

export function Mine({
  profile,
  go,
  future,
}: {
  profile: { xp: number; coins: number; level: number; topics: number; streak: number }
  go: (s: 'settings') => void
  future: (s: string) => void
}) {
  return (
    <>
      <View className="row">
        <View className="row">
          <View className="avatar large">我</View>
          <View>
            <View className="strong" style={{ fontSize: 23 }}>
              本机学习者
            </View>
            <View className="small muted">第 {profile.streak} 天，一点点变厉害</View>
          </View>
        </View>
        <View className="settings-entry" onClick={() => go('settings')}>
          <Icon name="settings" />
        </View>
      </View>
      <View className="panel blue mt">
        <View className="row">
          <Text className="strong">Lv. {profile.level} / 知识探险家</Text>
          <Text className="small">{profile.xp % 100} / 100 XP</Text>
        </View>
        <View className="progress-track mt">
          <View className="progress-fill" style={{ width: `${profile.xp % 100}%` }} />
        </View>
        <View className="small muted mt">
          再积累 {100 - (profile.xp % 100)} XP，开启下一段旅程。
        </View>
      </View>
      <Stat
        items={[
          [profile.topics, '学过主题'],
          [`${profile.streak} 天`, '连续学习'],
          [profile.coins, '金币余额'],
        ]}
      />
      <Row
        title="我的成就"
        sub="每个小进步，都值得留个纪念"
        icon="trophy"
        onClick={() => future('成就徽章')}
      />
      <Row
        title="私有知识库"
        sub="自己的笔记，自己的关卡"
        icon="folder"
        onClick={() => future('私有知识库')}
      />
      <Row
        title="好友挑战"
        sub="和学习搭子切磋一下"
        icon="flag"
        onClick={() => future('好友挑战')}
      />
      <Row
        title="搭子装扮"
        sub="用金币给学习留个纪念"
        icon="star"
        onClick={() => future('搭子装扮')}
      />
      <Row
        title="LevelU Plus"
        sub="查看高级学习权益"
        icon="shield"
        color="yellow"
        onClick={() => future('会员权益')}
      />
      <Row
        title="订单与权益记录"
        sub="后续开放"
        icon="file"
        onClick={() => future('订单与权益记录')}
      />
    </>
  )
}
export function SettingsView({
  go,
  future,
  exportRecords,
  notice,
}: {
  go: (s: 'data') => void
  future: (s: string) => void
  exportRecords: () => void
  notice: (kind: 'privacy' | 'terms') => void
}) {
  return (
    <>
      <Title>按自己的节奏学</Title>
      <View className="settings-group">
        <View className="settings-heading">学习偏好</View>
        <View className="setting-row" onClick={() => future('学习提醒')}>
          <Text>学习提醒</Text>
          <View className="toggle" />
        </View>
        <View className="setting-row" onClick={() => future('提醒时间')}>
          <Text>提醒时间</Text>
          <Text className="setting-value">20:30</Text>
        </View>
        <View className="setting-row" onClick={() => future('题目播报')}>
          <Text>题目播报</Text>
          <View className="toggle" />
        </View>
        <View className="setting-row" onClick={() => future('操作音效')}>
          <Text>操作音效</Text>
          <View className="toggle" />
        </View>
      </View>
      <View className="settings-group">
        <View className="settings-heading">学习数据</View>
        <View className="setting-row" onClick={exportRecords}>
          <Text>导出学习记录</Text>
          <Text className="text-btn">
            导出
            <Icon name="download" />
          </Text>
        </View>
        <View className="setting-row" onClick={() => go('data')}>
          <Text>数据与账户管理</Text>
          <Icon name="chevron" />
        </View>
        <View className="setting-row" onClick={() => future('意见反馈')}>
          <Text>意见反馈</Text>
          <Text className="text-btn">
            填写
            <Icon name="chevron" />
          </Text>
        </View>
      </View>
      <View className="settings-group">
        <View className="settings-heading">关于 LevelUProject</View>
        <View className="setting-row" onClick={() => notice('terms')}>
          <Text>用户协议</Text>
          <Icon name="chevron" />
        </View>
        <View className="setting-row" onClick={() => notice('privacy')}>
          <Text>隐私说明</Text>
          <Icon name="chevron" />
        </View>
        <View className="setting-row">
          <Text>应用版本</Text>
          <Text className="setting-value">MVP 1.0 / 2026.10.12</Text>
        </View>
      </View>
      <View className="notice">学习提醒、播报和音效将在后续版本开放。</View>
    </>
  )
}
