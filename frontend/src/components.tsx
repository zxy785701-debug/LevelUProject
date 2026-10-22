import React from 'react'
import { View, Text, Image, Button } from '@tarojs/components'
import u from './assets/u-book.png'
import pencil from './assets/pencil.png'
import paper from './assets/paper.png'
const icons = Object.fromEntries(
  (require as any)
    .context('./assets/icons', false, /\.png$/)
    .keys()
    .map((k: string) => [
      k.replace('./', '').replace('.png', ''),
      (require as any).context('./assets/icons', false, /\.png$/)(k),
    ]),
)
export function Icon({ name = 'spark', className = '' }: { name?: string; className?: string }) {
  return (
    <Image
      className={`icon ${className}`}
      src={icons[name]?.default || icons[name] || icons.spark}
      mode="aspectFit"
    />
  )
}
export function Mascot({ who = 'u', className = '' }: { who?: string; className?: string }) {
  return (
    <Image
      className={`mascot ${className}`}
      src={{ u, pencil, paper }[who] || u}
      mode="aspectFit"
    />
  )
}
export function Title({ children, sub }: { children: React.ReactNode; sub?: string }) {
  return (
    <>
      <View className="page-title">{children}</View>
      {sub && <View className="body-copy">{sub}</View>}
    </>
  )
}
export function Hero({
  children,
  sub,
  who = 'u',
}: {
  children: React.ReactNode
  sub: string
  who?: string
}) {
  return (
    <View className="hero-small">
      <Title sub={sub}>{children}</Title>
      <Mascot who={who} />
    </View>
  )
}
export function Stage({
  who = 'u',
  sticker = '',
  yellow = false,
}: {
  who?: string
  sticker?: string
  yellow?: boolean
}) {
  return (
    <View className={`hero-stage ${yellow ? 'yellow' : ''}`}>
      <Text className="spark">✧</Text>
      <Mascot who={who} />
      {sticker && <Text className="sticker">{sticker}</Text>}
    </View>
  )
}
export function Buddy({ children, who = 'u' }: { children: React.ReactNode; who?: string }) {
  return (
    <View className="buddy-note">
      <Mascot who={who} />
      <View className="bubble">{children}</View>
    </View>
  )
}
export function Btn({
  children,
  onClick,
  secondary = false,
  disabled = false,
  share = false,
}: {
  children: React.ReactNode
  onClick?: () => void
  secondary?: boolean
  disabled?: boolean
  share?: boolean
}) {
  return (
    <Button
      {...(process.env.TARO_ENV === 'h5' ? { role: 'button' } : { ariaRole: 'button' })}
      aria-label={typeof children === 'string' ? children : undefined}
      aria-disabled={disabled}
      className={`btn ${secondary ? 'secondary' : 'primary'} ${disabled ? 'is-disabled' : ''}`}
      disabled={disabled}
      onClick={disabled ? undefined : onClick}
      openType={share ? 'share' : undefined}
    >
      {children}
    </Button>
  )
}
export function Tag({ children, color = '' }: { children: React.ReactNode; color?: string }) {
  return <Text className={`tag ${color}`}>{children}</Text>
}
export function Section({
  children,
  link,
  onClick,
}: {
  children: React.ReactNode
  link?: string
  onClick?: () => void
}) {
  return (
    <View className="section-title">
      <Text>{children}</Text>
      {link && (
        <Text className="text-btn" onClick={onClick}>
          {link}
          <Icon name="chevron" />
        </Text>
      )}
    </View>
  )
}
export function Row({
  title,
  sub,
  icon = 'book',
  onClick,
  end,
  color = '',
  textLed = false,
  iconLabel,
}: {
  title: string
  sub?: string
  icon?: string
  onClick?: () => void
  end?: React.ReactNode
  color?: string
  textLed?: boolean
  iconLabel?: string
}) {
  return (
    <View className={`list-row ${textLed ? 'text-led' : ''}`} onClick={onClick}>
      {!textLed && (
        <View
          className={`icon-tile ${color}`}
          ariaRole={iconLabel ? 'img' : undefined}
          ariaLabel={iconLabel}
        >
          <Icon name={icon} />
        </View>
      )}
      <View className="list-text">
        <View className="strong">{title}</View>
        {sub && <View className="row-sub">{sub}</View>}
      </View>
      {end && <View className="list-end">{end}</View>}
      {onClick && <Icon name="chevron" className="chevron" />}
    </View>
  )
}
export function Stat({ items }: { items: (string | number)[][] }) {
  return (
    <View className="stat-grid">
      {items.map(([value, label]) => (
        <View key={label}>
          <View className="stat-value">{value}</View>
          <Text>{label}</Text>
        </View>
      ))}
    </View>
  )
}
export function Segments({
  items,
  value,
  onChange,
}: {
  items: string[]
  value: number
  onChange: (v: number) => void
}) {
  return (
    <View className="segmented">
      {items.map((x, i) => (
        <View key={x} className={i === value ? 'active' : ''} onClick={() => onChange(i)}>
          {x}
        </View>
      ))}
    </View>
  )
}
export function Chips({
  items,
  value,
  onChange,
}: {
  items: string[]
  value: number
  onChange: (v: number) => void
}) {
  return (
    <View className="chips">
      {items.map((x, i) => (
        <View key={x} className={i === value ? 'active' : ''} onClick={() => onChange(i)}>
          {x}
        </View>
      ))}
    </View>
  )
}
export function Mastery({
  label,
  value,
  color = 'blue',
}: {
  label: string
  value: number
  color?: string
}) {
  return (
    <View className="mastery">
      <View className="row">
        <Text>{label}</Text>
        <Text>{value}%</Text>
      </View>
      <View className={`progress-track ${color}`}>
        <View className="progress-fill" style={{ width: `${value}%` }} />
      </View>
    </View>
  )
}
export function Crew() {
  return (
    <View className="poster-crew">
      <Mascot who="pencil" />
      <Mascot />
      <Mascot who="paper" />
    </View>
  )
}
