import { useHealth } from '../../hooks/useHealth'

export function HealthPanel() {
  const { data: health, isLoading, error } = useHealth()

  return (
    <section className="bg-gray-900 rounded-lg p-5">
      <h2 className="text-lg font-semibold mb-3 text-white">System Health</h2>
      {isLoading && <p className="text-gray-400 text-sm">Checking...</p>}
      {error && <p className="text-red-400 text-sm">Connection failed</p>}
      {health && (
        <div>
          <p
            className={`text-sm font-medium mb-2 ${health.status === 'healthy' ? 'text-green-400' : 'text-yellow-400'}`}
          >
            {health.status}
          </p>
          <ul className="space-y-1">
            {Object.entries(health.checks).map(([name, st]) => (
              <li key={name} className="flex justify-between text-sm">
                <span className="text-gray-400">{name}</span>
                <span className={st === 'ok' ? 'text-green-400' : 'text-red-400'}>{st}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
