import { useState } from 'react'
import {
  useAgentConfigs,
  useCreateCustomAgent,
  useActivateAgent,
  useDeactivateAgent,
} from '../../hooks/useAgentBuilder'

const AVAILABLE_MODELS = [
  { label: 'Claude Sonnet', value: 'claude-sonnet' },
  { label: 'Claude Haiku', value: 'claude-haiku' },
  { label: 'Gemini Pro', value: 'gemini-pro' },
  { label: 'Gemini Flash', value: 'gemini-flash' },
]

const AVAILABLE_TOOLS = [
  'web_search',
  'web_fetch',
  'file_read',
  'file_write',
  'code_execute',
  'git_push',
  'send_email',
  'memory_read',
]

export function AgentBuilderPanel() {
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [role, setRole] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [model, setModel] = useState('claude-sonnet')
  const [selectedTools, setSelectedTools] = useState<string[]>([])
  const [tokenBudget, setTokenBudget] = useState('50000')

  const { data: agents, isLoading } = useAgentConfigs()
  const createAgent = useCreateCustomAgent()
  const activateAgent = useActivateAgent()
  const deactivateAgent = useDeactivateAgent()

  const toggleTool = (tool: string) => {
    setSelectedTools((prev) =>
      prev.includes(tool) ? prev.filter((t) => t !== tool) : [...prev, tool]
    )
  }

  const handleCreate = () => {
    if (!name.trim() || !systemPrompt.trim()) return
    createAgent.mutate(
      {
        name,
        role: role || undefined,
        system_prompt: systemPrompt,
        llm_model: model,
        tool_access: selectedTools.length > 0 ? selectedTools : undefined,
        token_budget_per_task: parseInt(tokenBudget, 10) || 50000,
      },
      {
        onSuccess: () => {
          setName('')
          setRole('')
          setSystemPrompt('')
          setModel('claude-sonnet')
          setSelectedTools([])
          setTokenBudget('50000')
          setShowCreate(false)
        },
      }
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <span className="text-2xl">🛠️</span> Agent Builder
        </h2>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="px-3 py-1 text-xs bg-indigo-600 text-white rounded-md hover:bg-indigo-500 transition-all"
        >
          {showCreate ? 'Cancel' : 'New Agent'}
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-400 block mb-1">Agent Name</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Data Scientist"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 block mb-1">
                Role (optional)
              </label>
              <input
                value={role}
                onChange={(e) => setRole(e.target.value)}
                placeholder="e.g., data_scientist"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
              />
            </div>
          </div>

          <div>
            <label className="text-xs text-gray-400 block mb-1">System Prompt</label>
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="Define the agent's behavior, expertise, and instructions..."
              rows={5}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none resize-none font-mono"
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-400 block mb-1">LLM Model</label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:border-indigo-500 focus:outline-none"
              >
                {AVAILABLE_MODELS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-400 block mb-1">
                Token Budget per Task
              </label>
              <input
                type="number"
                value={tokenBudget}
                onChange={(e) => setTokenBudget(e.target.value)}
                min="1000"
                step="1000"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
              />
            </div>
          </div>

          <div>
            <label className="text-xs text-gray-400 block mb-1">Tool Access</label>
            <div className="flex flex-wrap gap-2 mt-1">
              {AVAILABLE_TOOLS.map((tool) => (
                <button
                  key={tool}
                  onClick={() => toggleTool(tool)}
                  className={`px-2 py-1 rounded text-xs font-medium transition-all ${
                    selectedTools.includes(tool)
                      ? 'bg-indigo-600 text-white'
                      : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                  }`}
                >
                  {tool}
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={handleCreate}
            disabled={!name.trim() || !systemPrompt.trim() || createAgent.isPending}
            className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 disabled:opacity-50 transition-all"
          >
            {createAgent.isPending ? 'Creating...' : 'Create Agent'}
          </button>
        </div>
      )}

      {/* Agent list */}
      {isLoading ? (
        <div className="text-gray-500 text-sm animate-pulse">Loading agents...</div>
      ) : agents && agents.length > 0 ? (
        <div className="space-y-3">
          {agents.map((agent) => (
            <div
              key={agent.id}
              className="bg-gray-900 border border-gray-800 rounded-xl p-4 hover:border-gray-700 transition-colors"
            >
              <div className="flex items-start justify-between">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <h3 className="text-white font-semibold text-sm">{agent.name}</h3>
                    <span className="px-1.5 py-0.5 bg-gray-800 text-gray-300 rounded text-xs">
                      {agent.role}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium ${
                        agent.is_active
                          ? 'bg-green-950/50 text-green-400'
                          : 'bg-red-950/50 text-red-400'
                      }`}
                    >
                      {agent.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </div>
                  <div className="text-xs text-gray-500">
                    Model: {agent.llm_model} | Budget: {agent.token_budget_per_task.toLocaleString()} tokens
                  </div>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {agent.tool_access.map((tool) => (
                      <span
                        key={tool}
                        className="px-1.5 py-0.5 bg-gray-800 text-gray-400 rounded text-xs"
                      >
                        {tool}
                      </span>
                    ))}
                  </div>
                  <div className="text-xs text-gray-600 mt-1 font-mono line-clamp-2">
                    {agent.system_prompt}
                  </div>
                </div>
                <div className="flex gap-1 ml-4 shrink-0">
                  {agent.is_active ? (
                    <button
                      onClick={() => deactivateAgent.mutate(agent.id)}
                      disabled={deactivateAgent.isPending}
                      className="px-2 py-1 text-xs bg-red-900/50 text-red-400 rounded hover:bg-red-800/50 disabled:opacity-50 transition-all"
                    >
                      Deactivate
                    </button>
                  ) : (
                    <button
                      onClick={() => activateAgent.mutate(agent.id)}
                      disabled={activateAgent.isPending}
                      className="px-2 py-1 text-xs bg-green-800/50 text-green-300 rounded hover:bg-green-700/50 disabled:opacity-50 transition-all"
                    >
                      Activate
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-gray-500 text-sm">
          No custom agents configured. Create one to get started.
        </div>
      )}
    </div>
  )
}
