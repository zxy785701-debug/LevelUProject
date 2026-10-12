import React, { createContext, useContext, useRef, useState } from 'react'
import Taro from '@tarojs/taro'
import { Action, Data, emptyData, reducer } from './domain'
const KEY = 'levelup.local.v1'
function read(): Data {
  try {
    const d = Taro.getStorageSync(KEY)
    if (d && d.version === 1 && Array.isArray(d.sessions) && d.wrongs && d.draft) return d
  } catch {}
  return emptyData()
}
const Context = createContext<{ data: Data; dispatch: (a: Action) => boolean }>({
  data: emptyData(),
  dispatch: () => false,
})
export function Provider({ children }: { children: React.ReactNode }) {
  const [data, setData] = useState(read),
    ref = useRef(data)
  function dispatch(a: Action) {
    const next = reducer(ref.current, a)
    if (next === ref.current) return true
    try {
      Taro.setStorageSync(KEY, next)
      ref.current = next
      setData(next)
      return true
    } catch {
      void Taro.showModal({
        title: '记录暂时无法保存',
        content: '本机存储空间可能不足。请释放空间后重试，当前操作尚未提交。',
        showCancel: false,
      })
      return false
    }
  }
  return <Context.Provider value={{ data, dispatch }}>{children}</Context.Provider>
}
export const useStore = () => useContext(Context)
