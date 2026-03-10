import { useEffect, useState } from 'react'

export function Layout({ children }: { children: React.ReactNode }) {
  const [dark, setDark] = useState(() => {
    const stored = localStorage.getItem('nexus-theme')
    return stored ? stored === 'dark' : true
  })

  useEffect(() => {
    document.documentElement.classList.toggle('light-mode', !dark)
    localStorage.setItem('nexus-theme', dark ? 'dark' : 'light')
  }, [dark])

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 p-6 transition-colors">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight">NEXUS</h1>
          <p className="text-gray-500 text-sm mt-1">Agentic AI Company as a Service</p>
        </div>
        <button
          onClick={() => setDark((v) => !v)}
          className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm transition-all"
          title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {dark ? '☀️ Light' : '🌙 Dark'}
        </button>
      </header>
      <div className="max-w-6xl mx-auto space-y-4">{children}</div>
    </div>
  )
}
