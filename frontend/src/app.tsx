import React from 'react'
import { AuthProvider } from './auth'
import './app.scss'
export default function App({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>
}
