import { useAgents } from '../../hooks/useAgents'

const ROLE_CONFIG: Record<string, { emoji: string; color: string; label: string }> = {
  ceo: { emoji: '👔', color: 'border-amber-500', label: 'Chief Executive' },
  engineer: { emoji: '💻', color: 'border-blue-500', label: 'Engineer' },
  analyst: { emoji: '🔍', color: 'border-purple-500', label: 'Analyst' },
  writer: { emoji: '✍️', color: 'border-green-500', label: 'Writer' },
  qa: { emoji: '🛡️', color: 'border-red-500', label: 'Quality Assurance' },
  prompt_creator: { emoji: '🧪', color: 'border-cyan-500', label: 'Prompt Creator' },
}

export function AgentOrgChart() {
  const { data: agents, isLoading } = useAgents()

  if (isLoading) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 text-center text-gray-500 text-sm animate-pulse">
        Loading organization chart...
      </div>
    )
  }

  if (!agents || agents.length === 0) {
    return null
  }

  const ceo = agents.find((a) => a.role === 'ceo')
  const specialists = agents.filter((a) => a.role !== 'ceo')

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800">
        <h2 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
          <span>🏢</span> Organization Chart
        </h2>
      </div>

      <div className="p-6">
        {/* CEO at top */}
        {ceo && (
          <div className="flex flex-col items-center mb-6">
            <AgentNode agent={ceo} isCeo />
            {/* Connection line */}
            <div className="w-px h-6 bg-gray-700" />
            <div
              className="border-t border-gray-700"
              style={{
                width: `${Math.min(specialists.length * 140, 700)}px`,
              }}
            />
          </div>
        )}

        {/* Specialists in a row */}
        <div className="flex flex-wrap justify-center gap-4">
          {specialists.map((agent) => (
            <div key={agent.id} className="flex flex-col items-center">
              <div className="w-px h-4 bg-gray-700" />
              <AgentNode agent={agent} />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function AgentNode({
  agent,
  isCeo = false,
}: {
  agent: { id: string; role: string; name: string; llm_model: string; is_active: boolean; tool_access: string[] }
  isCeo?: boolean
}) {
  const config = ROLE_CONFIG[agent.role] || { emoji: '🤖', color: 'border-gray-500', label: agent.role }

  return (
    <div
      className={`
        relative bg-gray-800 rounded-xl border-2 ${config.color}
        ${isCeo ? 'px-6 py-4 min-w-[200px]' : 'px-4 py-3 min-w-[160px]'}
        transition-all hover:brightness-110 hover:shadow-lg hover:shadow-${config.color.replace('border-', '')}/10
      `}
    >
      {/* Status indicator */}
      <div
        className={`absolute top-2 right-2 w-2 h-2 rounded-full ${
          agent.is_active ? 'bg-green-400 animate-pulse' : 'bg-gray-600'
        }`}
        title={agent.is_active ? 'Active' : 'Inactive'}
      />

      <div className="text-center">
        <div className={`${isCeo ? 'text-3xl' : 'text-2xl'} mb-1`}>{config.emoji}</div>
        <div className={`font-semibold text-white ${isCeo ? 'text-base' : 'text-sm'}`}>
          {agent.name}
        </div>
        <div className="text-xs text-gray-400 mt-0.5">{config.label}</div>
        <div className="text-[10px] text-gray-600 mt-1 font-mono truncate max-w-[130px]">
          {agent.llm_model}
        </div>
        {agent.tool_access.length > 0 && (
          <div className="flex flex-wrap gap-1 justify-center mt-2">
            {agent.tool_access.slice(0, 3).map((tool) => (
              <span
                key={tool}
                className="text-[9px] bg-gray-700 text-gray-400 px-1.5 py-0.5 rounded"
              >
                {tool.replace('tool_', '')}
              </span>
            ))}
            {agent.tool_access.length > 3 && (
              <span className="text-[9px] text-gray-500">+{agent.tool_access.length - 3}</span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
