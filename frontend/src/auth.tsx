import React, { createContext, useContext, useEffect, useState } from 'react'
import Taro from '@tarojs/taro'
import { View, Text, Checkbox, CheckboxGroup, ScrollView } from '@tarojs/components'
import { api, User } from './api'
import { credentials, clearCredentials, saveCredentials, onCredentialsCleared } from './credentials'
import { Btn, Stage, Title, Icon } from './components'
export const AGREEMENT = '2026-10-12'
export const PRIVACY = '登录身份、资料、题库、作答、错题和报告保存在服务端 MySQL，用于账号同步与学习统计。AI 生成时，学习材料及本轮作答发送至后端和 DeepSeek。头像昵称可选。退出登录撤销当前会话；注销删除资料和学习数据，当期防刷身份摘要和计数在额度周期结束后清理。'
export const TERMS = 'AI 出题和讲解可能有误，请结合原始资料核实。新生成关卡每题首次答对：入门 10 XP、2 金币，进阶 15 XP、3 金币；历史关卡沿用原奖励。每 100 XP 升一级，重闯和复习不重复发奖。每日出题与 AI 调用受额度限制；已开始的模型调用失败也占用额度。'
const Auth = createContext<{ user: User; update: (u: User) => void; logout: () => Promise<void>; loading: boolean; loginView: React.ReactNode }>({ user: null as unknown as User, update: () => {}, logout: async () => {}, loading: true, loginView: null })
export const useAuth = () => useContext(Auth)
export async function wechatCode() {
  if (process.env.TARO_ENV !== 'weapp') throw new Error('请在微信小程序中登录；H5 仅用于预览和测试。')
  const r = await Taro.login()
  if (!r.code) throw new Error('微信未返回登录凭证，请重试')
  return r.code
}
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User>(), [loading, setLoading] = useState(!!credentials().token), [error, setError] = useState(''), [agreed, setAgreed] = useState(false)
  async function restore() {
    if (!credentials().token) { setLoading(false); return }
    setLoading(true)
    try { setUser(await api<User>('/api/v1/me')); setError('') }
    catch (e) { setError((e as Error).message) }
    finally { setLoading(false) }
  }
  useEffect(() => {
    void restore()
    return onCredentialsCleared(() => { setUser(undefined); setError('请重新微信登录'); setLoading(false) })
  }, [])
  async function login() {
    if (!agreed || loading) return
    setLoading(true); setError('')
    try {
      const code = await wechatCode()
      const r = await api<{ token: string; user: User }>('/api/v1/auth/wechat', 'POST', { code, agreement_version: AGREEMENT })
      saveCredentials(r.token)
      setUser(r.user)
    } catch (e) { setError((e as Error).message) }
    finally { setLoading(false) }
  }
  async function logout() { await api('/api/v1/auth/logout', 'POST'); clearCredentials() }
  const loginView = <View className="app-shell footer-refined" data-id="A02">
    <View className="status-bar native" style={{ height: process.env.TARO_ENV === 'weapp' ? Taro.getWindowInfo().statusBarHeight || 20 : 33 }} />
    <View className="mini-bar"><Text className="mini-label">登录 LevelUProject</Text></View>
    <ScrollView scrollY className="phone-scroll"><View className="content">
      <Stage who="u" sticker="让知识跟着你走" />
      <Title sub="登录后，学习记录、错题和报告可以与你的账户关联。">保存你的学习旅程</Title>
      <View className="panel blue mt"><View className="stack">
        {['跨设备查看学习档案', '保留闯关进度与错题', '累计个人 XP 和金币'].map(text => <View className="small" key={text}><Icon name="check" />{text}</View>)}
      </View></View>
      <CheckboxGroup onChange={e => setAgreed(e.detail.value.includes('agree'))}>
        <View className="check-label mt"><Checkbox value="agree" checked={agreed} />我已阅读并同意
          <Text className="inline-link" onClick={() => void Taro.showModal({ title: '用户协议', content: TERMS, showCancel: false })}>用户协议</Text>与
          <Text className="inline-link" onClick={() => void Taro.showModal({ title: '隐私说明', content: PRIVACY, showCancel: false })}>隐私说明</Text>
        </View>
      </CheckboxGroup>
      {error && <View className="notice">{error}</View>}
      {process.env.TARO_ENV !== 'weapp' && <View className="notice">请在微信小程序中登录。此 H5 页面仅用于预览与测试。</View>}
    </View></ScrollView>
    <View className="phone-bottom"><Btn disabled={!agreed || loading} onClick={login}>{loading ? '正在验证登录…' : '微信登录'}</Btn>
      {!!credentials().token && !loading && <Btn secondary onClick={restore}>重新连接</Btn>}
    </View>
  </View>
  return <Auth.Provider value={{ user: user as User, update: setUser, logout, loading, loginView }}>{children}</Auth.Provider>
}
