import React from 'react'
import { Button, Checkbox, Image, Radio, Text, View } from '@tarojs/components'
import { Tag, Title } from './components'
import { knowledgeStatus } from './knowledge-domain'
import type { KnowledgeDocument } from './knowledge-domain'

const buttonRole = process.env.TARO_ENV === 'h5' ? { role: 'button' } : { ariaRole: 'button' }
export function KnowledgeActionButton(props: React.ComponentProps<typeof Button>) {
  return <Button {...buttonRole} {...props} />
}
const icons = (require as any).context('./assets/knowledge-icons', false, /\.png$/)
export function KnowledgeIcon({
  name,
  tone = 'blue',
  className = '',
}: {
  name: string
  tone?: 'blue' | 'white' | 'muted' | 'red'
  className?: string
}) {
  const asset = icons(`./${name}-${tone}.png`)
  return <Image className={`icon ${className}`} src={asset.default || asset} mode="aspectFit" />
}
export function KnowledgeChoice({
  checked,
  value,
  radio = false,
}: {
  checked: boolean
  value: string
  radio?: boolean
}) {
  return (
    <View className="knowledge-choice-control">
      {radio ? (
        <Radio
          className="knowledge-choice-native"
          value={value}
          checked={checked}
          color="#336ae8"
        />
      ) : (
        <Checkbox
          className="knowledge-choice-native"
          value={value}
          checked={checked}
          color="#336ae8"
        />
      )}
      <View
        aria-hidden
        className={`knowledge-choice-box${radio ? ' radio' : ''}${checked ? ' checked' : ''}`}
      />
    </View>
  )
}
export const knowledgeBytes = (bytes: number) =>
  bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : bytes >= 1024
      ? `${(bytes / 1024).toFixed(1)} KB`
      : `${bytes} B`
export function KnowledgeTitle({ text, mark, sub }: { text: string; mark?: string; sub?: string }) {
  const at = mark ? text.lastIndexOf(mark) : -1
  return (
    <Title sub={sub}>
      {at < 0 ? (
        text
      ) : (
        <>
          {text.slice(0, at)}
          <Text className="handline">{mark}</Text>
          {text.slice(at + mark!.length)}
        </>
      )}
    </Title>
  )
}
export function KnowledgeRow({
  title,
  sub,
  icon = 'folder',
  onClick,
  end,
  disabled = false,
}: {
  title: string
  sub?: string
  icon?: string
  onClick?: () => void
  end?: React.ReactNode
  disabled?: boolean
}) {
  return (
    <Button
      {...buttonRole}
      className="list-row knowledge-row"
      aria-label={title}
      disabled={disabled}
      onClick={onClick}
    >
      <View className="icon-tile">
        <KnowledgeIcon name={icon} />
      </View>
      <View className="list-text">
        <View className="strong">{title}</View>
        {sub && <View className="row-sub">{sub}</View>}
      </View>
      {end && <View className="list-end">{end}</View>}
      <KnowledgeIcon name="chevron" tone="muted" className="chevron" />
    </Button>
  )
}
export function knowledgeUpdated(value: string | number) {
  const date = new Date(value),
    today = new Date()
  if (!Number.isFinite(date.getTime())) return '已保存'
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const delta = day(today) - day(date)
  return delta === 0
    ? '今天更新'
    : delta === 86400000
      ? '昨天更新'
      : `${date.getMonth() + 1} 月 ${date.getDate()} 日更新`
}
export function KnowledgeFileCard({
  document,
  onClick,
}: {
  document: KnowledgeDocument
  onClick: () => void
}) {
  return (
    <Button
      {...buttonRole}
      className="file-card knowledge-file-card"
      aria-label={'查看资料：' + document.title}
      onClick={onClick}
    >
      <View className="icon-tile">
        <KnowledgeIcon name={document.source_type === 'web' ? 'link' : 'file'} />
      </View>
      <View className="file-details">
        <View className="strong">{document.title}</View>
        <View className="small muted">
          {document.source_type === 'web' ? '网页' : document.source_type.toUpperCase()} /{' '}
          {document.chunk_count
            ? document.chunk_count + ' 个片段'
            : knowledgeUpdated(document.updated_at)}
        </View>
      </View>
      <Tag
        color={
          document.status === 'ready' ? 'green' : document.status === 'failed' ? 'red' : 'blue'
        }
      >
        {knowledgeStatus(document.status)}
      </Tag>
    </Button>
  )
}
