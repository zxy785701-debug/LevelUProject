import React, { createContext, useContext, useEffect, useRef, useState } from 'react'
import Taro from '@tarojs/taro'
import { Action, Data, Session, emptyData, reducer } from './domain'
import { getLearning } from './api'
import { useAuth } from './auth'
const Context = createContext<{ data: Data; dispatch: (a: Action) => boolean; upsert: (s: Session) => void; refresh: (wrongsOnly?: boolean) => Promise<void>; loading: boolean; error: string }>({ data: emptyData(), dispatch: () => false, upsert: () => {}, refresh: async () => {}, loading: true, error: '' })
export function Provider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  const key = 'levelup.account.v1.' + user.id
  const [data, setData] = useState<Data>(() => {
    try { const cached = Taro.getStorageSync(key); if (cached?.version === 1) return cached } catch {}
    return { ...emptyData(), welcome: true }
  })
  const ref = useRef(data), alive = useRef(true)
  const [loading, setLoading] = useState(true), [error, setError] = useState('')
  function commit(next: Data) {
    if (!alive.current) return
    ref.current = next; setData(next)
    try { Taro.setStorageSync(key, next) } catch { setError('云端记录已保存，本机缓存暂时无法写入。') }
  }
  async function refresh(wrongsOnly = false) {
    try {
      const remote = await getLearning()
      if (alive.current) { commit(wrongsOnly ? { ...ref.current, wrongs: remote.wrongs } : { ...remote, activeId: ref.current.activeId && remote.sessions.some(s => s.id === ref.current.activeId) ? ref.current.activeId : remote.activeId, draft: ref.current.draft }); setError('') }
    } catch (e) { if (alive.current) setError((e as Error).message); throw e }
    finally { if (alive.current) setLoading(false) }
  }
  useEffect(() => { alive.current = true; void refresh().catch(() => {}); return () => { alive.current = false } }, [])
  function dispatch(a: Action) {
    if (a.type === 'CLEAR_CACHE') {
      const next = reducer(ref.current, a)
      ref.current = next; setData(next)
      try { Taro.removeStorageSync(key) } catch {}
    } else commit(reducer(ref.current, a))
    return true
  }
  function upsert(session: Session) {
    const exists = ref.current.sessions.some(s => s.id === session.id)
    commit({ ...ref.current, activeId: session.id, sessions: exists ? ref.current.sessions.map(s => s.id === session.id ? session : s) : [...ref.current.sessions, session] })
  }
  return <Context.Provider value={{ data, dispatch, upsert, refresh, loading, error }}>{children}</Context.Provider>
}
export const useStore = () => useContext(Context)
