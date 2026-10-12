import React, { createContext, useContext, useRef, useState } from 'react'
import Taro from '@tarojs/taro'
import { Action, Data, emptyData } from './domain'
import { STORAGE_KEY } from './learning'
import { commitData, readData } from './storage'
const Context = createContext<{data:Data; dispatch:(a:Action)=>boolean}>({data:emptyData(),dispatch:()=>false})
export function Provider({children}:{children:React.ReactNode}) {
  const [data,setData]=useState(()=>readData(()=>Taro.getStorageSync(STORAGE_KEY))), ref=useRef(data)
  const dispatch=(action:Action)=>{
    try {
      const next=commitData(ref.current,action,d=>Taro.setStorageSync(STORAGE_KEY,d))
      ref.current=next;setData(next);return true
    } catch {
      void Taro.showModal({title:'记录暂时无法保存',content:'本机存储空间可能不足。请释放空间后重试，当前操作尚未提交。',showCancel:false})
      return false
    }
  }
  return <Context.Provider value={{data,dispatch}}>{children}</Context.Provider>
}
export const useStore=()=>useContext(Context)
