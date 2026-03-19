import { useAgents } from '../../hooks/useAgents'
import { Skeleton } from '../ui/skeleton'

export function AgentStatusPanel() {
  const { data: agents = [], isLoading } = useAgents()

  if (isLoading) {
    return (
      <section className="bg-gray-900 rounded-lg p-5">
        <h2 className="text-lg font-semibold mb-3 text-white">Agents</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      </section>
    )
  }

  return (
    <section className="bg-gray-900 rounded-lg p-5">
      <h2 className="text-lg font-semibold mb-3 text-white">
        Agents
        <span className="ml-2 text-sm text-gray-500 font-normal">({agents.length})</span>
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {agents.map((agent) => (
          <div key={agent.id} className="border border-gray-700 rounded-lg p-4 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-white">{agent.name}</span>
              <span
                className={`px-2 py-0.5 rounded text-xs font-medium ${agent.is_active ? 'bg-green-800 text-green-200' : 'bg-gray-700 text-gray-400'}`}
              >
                {agent.is_active ? 'Active' : 'Inactive'}
              </span>
            </div>
            <div className="text-xs text-gray-400 space-y-1">
              <p>
                Role: <span className="text-gray-300">{agent.role}</span>
              </p>
              <p>
                Model: <span className="text-gray-300">{agent.llm_model}</span>
              </p>
              <p>
                Token budget:{' '}
                <span className="text-gray-300">
                  {agent.token_budget_per_task.toLocaleString()}
                </span>
              </p>
              {agent.tool_access.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {agent.tool_access.map((tool) => (
                    <span key={tool} className="px-1.5 py-0.5 bg-gray-800 rounded text-xs text-gray-300">
                      {tool}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
