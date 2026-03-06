import { useQuery } from '@tanstack/react-query'

const API_URL = import.meta.env.VITE_API_URL || ''

interface HealthCheck {
  status: string
  checks: Record<string, string>
}

function App() {
  const { data: health, isLoading, error } = useQuery<HealthCheck>({
    queryKey: ['health'],
    queryFn: async () => {
      const res = await fetch(`${API_URL}/health`)
      return res.json()
    },
    refetchInterval: 10000,
  })

  return (
    <div className="min-h-screen p-8">
      <header className="mb-8">
        <h1 className="text-4xl font-bold text-white">NEXUS</h1>
        <p className="text-gray-400 mt-1">Agentic AI Company as a Service</p>
      </header>

      <section className="bg-gray-900 rounded-lg p-6 max-w-xl">
        <h2 className="text-xl font-semibold mb-4">System Health</h2>
        {isLoading && <p className="text-gray-400">Checking...</p>}
        {error && <p className="text-red-400">Connection failed</p>}
        {health && (
          <div>
            <p className={`text-lg font-medium mb-3 ${
              health.status === 'healthy' ? 'text-green-400' : 'text-yellow-400'
            }`}>
              Status: {health.status}
            </p>
            <ul className="space-y-1">
              {Object.entries(health.checks).map(([name, status]) => (
                <li key={name} className="flex justify-between">
                  <span className="text-gray-300">{name}</span>
                  <span className={status === 'ok' ? 'text-green-400' : 'text-red-400'}>
                    {status}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </div>
  )
}

export default App
