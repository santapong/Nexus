export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 p-6">
      <header className="mb-6">
        <h1 className="text-3xl font-bold text-white tracking-tight">NEXUS</h1>
        <p className="text-gray-500 text-sm mt-1">Agentic AI Company as a Service</p>
      </header>
      <div className="max-w-4xl mx-auto space-y-4">{children}</div>
    </div>
  )
}
