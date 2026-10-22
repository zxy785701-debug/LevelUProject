import React, { useEffect, useRef, useState } from 'react'
import Taro from '@tarojs/taro'
import { View, Text, Image, Button, Form, Input } from '@tarojs/components'
import { useAuth } from './auth'
import { api, User, uploadAvatar, downloadAvatar } from './api'
import { Icon, Title, Stat, Row } from './components'
import { saveAvatarImage } from './platform'

export function Mine({
  profile,
  go,
  future,
  onKnowledge,
}: {
  profile: { xp: number; coins: number; level: number; topics: number; streak: number }
  go: (s: 'settings') => void
  future: (s: string) => void
  onKnowledge?: () => void
}) {
  const { user, update } = useAuth()
  const [avatar, setAvatar] = useState(''), [editing, setEditing] = useState(false), [saving, setSaving] = useState(false)
  const [nicknameDraft, setNicknameDraft] = useState(user.nickname)
  const saveBusy = useRef(false)
  const [avatarMenu, setAvatarMenu] = useState(false), [avatarPreview, setAvatarPreview] = useState(false), [avatarBusy, setAvatarBusy] = useState(false)
  useEffect(() => {
    let alive = true
    setAvatar('')
    if (user.avatar_version) void downloadAvatar().then(path => { if (alive) setAvatar(path) }).catch(() => {})
    return () => { alive = false }
  }, [user.id, user.avatar_version])
  async function saveNickname(value: string) {
    if (saveBusy.current) return
    saveBusy.current = true
    setSaving(true)
    try { update(await api<User>('/api/v1/me', 'PUT', { nickname: value })); setEditing(false) }
    catch (e) { void Taro.showModal({ title: '昵称未保存', content: (e as Error).message, showCancel: false }) }
    finally { setSaving(false); saveBusy.current = false }
  }
  async function avatarAction(save: boolean) {
    if (avatarBusy || !user.avatar_version) return
    setAvatarBusy(true)
    try {
      const path = avatar || await downloadAvatar()
      setAvatar(path)
      if (save) {
        await saveAvatarImage(path)
        void Taro.showToast({ title: process.env.TARO_ENV === 'h5' ? '头像已下载' : '头像已保存', icon: 'success' })
      } else setAvatarPreview(true)
      setAvatarMenu(false)
    } catch (e) { void Taro.showModal({ title: '头像暂时无法操作', content: (e as Error).message, showCancel: false }) }
    finally { setAvatarBusy(false) }
  }
  async function chooseAvatar(path: string) {
    if (avatarBusy) return
    setAvatarBusy(true)
    try { update(await uploadAvatar(path)); setAvatarMenu(false) }
    catch (e) { void Taro.showModal({ title: '头像未保存', content: (e as Error).message, showCancel: false }) }
    finally { setAvatarBusy(false) }
  }
  return (
    <>
      <View className="row">
        <View className="row">
          <Button className="avatar large profile-avatar" onClick={() => setAvatarMenu(true)} aria-label="头像操作">{avatar ? <Image src={avatar} mode="aspectFill" className="profile-avatar-image" /> : '我'}</Button>
          <View>
            <View className="strong" style={{ fontSize: 23 }} onClick={() => { setNicknameDraft(user.nickname); setEditing(true) }}>
              {user.nickname}
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
        onClick={onKnowledge || (() => future('私有知识库'))}
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
      {avatarMenu && <View className="sheet-overlay"><View className="sheet avatar-actions">
        <View className="sheet-handle" />
        <View className="sheet-title">头像</View>
        {!user.avatar_version && <View className="small muted mb">先选择头像，即可查看或保存。</View>}
        <Button className={`btn secondary ${!user.avatar_version || avatarBusy ? 'is-disabled' : ''}`} disabled={!user.avatar_version || avatarBusy} onClick={() => void avatarAction(false)}>查看头像</Button>
        <Button className={`btn primary ${!user.avatar_version || avatarBusy ? 'is-disabled' : ''}`} disabled={!user.avatar_version || avatarBusy} onClick={() => void avatarAction(true)}>{avatarBusy ? '正在处理…' : '保存头像图片'}</Button>
        <Button className="btn secondary" disabled={avatarBusy} openType="chooseAvatar" onChooseAvatar={e => void chooseAvatar(e.detail.avatarUrl)}>更换头像</Button>
        <Button className="btn secondary" disabled={avatarBusy} onClick={() => setAvatarMenu(false)}>取消</Button>
      </View></View>}
      {avatarPreview && <View className="global-dialog"><View className="dialog-card">
        <View className="dialog-title">我的头像</View>
        <Image className="avatar-preview-image" src={avatar} mode="aspectFit" />
        <Button className="btn primary" disabled={avatarBusy} onClick={() => void avatarAction(true)}>保存头像图片</Button>
        <Button className="btn secondary" onClick={() => setAvatarPreview(false)}>关闭</Button>
      </View></View>}
      {editing && <View className="global-dialog"><View className="dialog-card">
        <View className="dialog-title">编辑昵称</View>
        <Form onSubmit={e => void saveNickname(String(e.detail.value?.nickname || '').trim())}>
          <Input className="profile-nickname" name="nickname" type="nickname" maxlength={32} value={nicknameDraft} onInput={e => setNicknameDraft(e.detail.value)} placeholder="填写你的昵称" />
          <Button className="btn primary" formType="submit" disabled={saving} onClick={process.env.TARO_ENV === 'h5' ? () => void saveNickname(nicknameDraft.trim()) : undefined}>{saving ? '正在保存…' : '保存昵称'}</Button>
        </Form>
        <Button className="btn secondary" onClick={() => setEditing(false)}>暂不修改</Button>
      </View></View>}
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
