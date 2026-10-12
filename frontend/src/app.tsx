import React from 'react'
import { Provider } from './store'
import './app.scss'
export default function App({ children }: { children: React.ReactNode }) {
  return <Provider>{children}</Provider>
}
