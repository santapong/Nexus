import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { AppHeader } from './AppHeader'
import { AgentWebSocketProvider } from '@/ws/AgentWebSocketProvider'

export function AppLayout() {
  const [dark, setDark] = useState(() => {
    const stored = localStorage.getItem('nexus-theme')
    return stored ? stored === 'dark' : true
  })

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    document.documentElement.classList.toggle('light-mode', !dark)
    localStorage.setItem('nexus-theme', dark ? 'dark' : 'light')
  }, [dark])

  return (
    <AgentWebSocketProvider>
      <div className="min-h-screen bg-gray-950 text-gray-100">
        <Sidebar dark={dark} onToggleTheme={() => setDark((v) => !v)} />
        <div className="md:pl-60">
          <AppHeader />
          <main className="p-6">
            <div className="max-w-6xl mx-auto space-y-6">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
    </AgentWebSocketProvider>
  )
}
