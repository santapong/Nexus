import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { usePerformance, useCosts, useDeadLetters } from '../../hooks/useAnalytics'
import { api } from '../../api/client'

const PERIODS = ['7d', '30d', '90d', 'all'] as const

export function AnalyticsDashboard() {
  const [period, setPeriod] = useState<string>('30d')
  const { data: perf, isLoading: perfLoading } = usePerformance(period)
  const { data: costs, isLoading: costLoading } = useCosts(period)
  const { data: deadLetters } = useDeadLetters()

  return (
    <div className="space-y-6">
      {/* Header with period selector */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <span className="text-2xl">📊</span> Analytics
        </h2>
        <div className="flex gap-1 bg-gray-800 rounded-lg p-1">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-3 py-1 text-xs rounded-md transition-all ${
                period === p
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              {p === 'all' ? 'All Time' : p}
            </button>
          ))}
        </div>
      </div>

      {/* Summary cards */}
      {perf && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <SummaryCard
            label="Total Tasks"
            value={perf.total_tasks.toString()}
            icon="📋"
          />
          <SummaryCard
            label="Success Rate"
            value={`${perf.overall_success_rate}%`}
            icon="✅"
            color={perf.overall_success_rate >= 80 ? 'text-green-400' : 'text-yellow-400'}
          />
          <SummaryCard
            label="Total Cost"
            value={`$${perf.total_cost_usd.toFixed(4)}`}
            icon="💰"
          />
          <SummaryCard
            label="Daily Avg"
            value={costs ? `$${costs.daily_average_usd.toFixed(4)}` : '—'}
            icon="📈"
          />
        </div>
      )}

      {/* Agent Performance Table */}
      {perfLoading ? (
        <div className="text-gray-500 text-sm animate-pulse">Loading performance data...</div>
      ) : perf && perf.agents.length > 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-800">
            <h3 className="text-sm font-semibold text-gray-300">Agent Performance</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs uppercase tracking-wider">
                  <th className="text-left px-4 py-2">Agent</th>
                  <th className="text-right px-4 py-2">Tasks</th>
                  <th className="text-right px-4 py-2">Success</th>
                  <th className="text-right px-4 py-2">Avg Tokens</th>
                  <th className="text-right px-4 py-2">Avg Duration</th>
                  <th className="text-right px-4 py-2">Cost</th>
                </tr>
              </thead>
              <tbody>
                {perf.agents.map((agent) => (
                  <tr key={agent.role} className="border-t border-gray-800 hover:bg-gray-800/50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="text-base">{roleEmoji(agent.role)}</span>
                        <div>
                          <div className="text-white font-medium">{agent.name}</div>
                          <div className="text-gray-500 text-xs">{agent.role}</div>
                        </div>
                      </div>
                    </td>
                    <td className="text-right px-4 py-3 text-gray-300">{agent.total_tasks}</td>
                    <td className="text-right px-4 py-3">
                      <span className={agent.success_rate >= 80 ? 'text-green-400' : agent.success_rate >= 50 ? 'text-yellow-400' : 'text-red-400'}>
                        {agent.success_rate}%
                      </span>
                    </td>
                    <td className="text-right px-4 py-3 text-gray-300">
                      {agent.avg_tokens > 0 ? agent.avg_tokens.toLocaleString() : '—'}
                    </td>
                    <td className="text-right px-4 py-3 text-gray-300">
                      {agent.avg_duration_seconds ? `${agent.avg_duration_seconds}s` : '—'}
                    </td>
                    <td className="text-right px-4 py-3 text-gray-300">
                      ${agent.total_cost_usd.toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="text-gray-500 text-sm">No performance data available yet.</div>
      )}

      {/* Cost by Model */}
      {costLoading ? (
        <div className="text-gray-500 text-sm animate-pulse">Loading cost data...</div>
      ) : costs && costs.by_model.length > 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-800">
            <h3 className="text-sm font-semibold text-gray-300">Cost by Model</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs uppercase tracking-wider">
                  <th className="text-left px-4 py-2">Model</th>
                  <th className="text-right px-4 py-2">Calls</th>
                  <th className="text-right px-4 py-2">Input Tokens</th>
                  <th className="text-right px-4 py-2">Output Tokens</th>
                  <th className="text-right px-4 py-2">Cost</th>
                </tr>
              </thead>
              <tbody>
                {costs.by_model.map((model) => (
                  <tr key={model.model_name} className="border-t border-gray-800 hover:bg-gray-800/50 transition-colors">
                    <td className="px-4 py-3 text-white font-mono text-xs">{model.model_name}</td>
                    <td className="text-right px-4 py-3 text-gray-300">{model.total_calls}</td>
                    <td className="text-right px-4 py-3 text-gray-300">{model.total_input_tokens.toLocaleString()}</td>
                    <td className="text-right px-4 py-3 text-gray-300">{model.total_output_tokens.toLocaleString()}</td>
                    <td className="text-right px-4 py-3 text-green-400">${model.total_cost_usd.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {/* Dead Letter Queue */}
      {deadLetters && deadLetters.total_dead_letters > 0 && (
        <DeadLetterSection deadLetters={deadLetters} />
      )}
    </div>
  )
}

function SummaryCard({
  label,
  value,
  icon,
  color = 'text-white',
}: {
  label: string
  value: string
  icon: string
  color?: string
}) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 transition-all hover:border-gray-700">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-lg">{icon}</span>
        <span className="text-xs text-gray-500 uppercase tracking-wider">{label}</span>
      </div>
      <div className={`text-xl font-bold ${color}`}>{value}</div>
    </div>
  )
}

function DeadLetterSection({ deadLetters }: { deadLetters: { total_dead_letters: number; unresolved: number; by_topic: Array<{ topic: string; count: number; oldest: string | null; newest: string | null }> } }) {
  const queryClient = useQueryClient()
  const resolveMutation = useMutation({
    mutationFn: (id: string) => api.resolveDeadLetter(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['analytics', 'dead-letters'] })
    },
  })

  return (
    <div className="bg-red-950/30 border border-red-800/50 rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-red-400">
          Dead Letter Queue — {deadLetters.total_dead_letters} failed
          {deadLetters.unresolved > 0 && (
            <span className="text-red-300 font-normal ml-2">
              ({deadLetters.unresolved} unresolved)
            </span>
          )}
        </h3>
      </div>
      <div className="space-y-2">
        {deadLetters.by_topic
          .filter((t) => t.count > 0)
          .map((t) => (
            <div key={t.topic} className="flex items-center justify-between bg-red-950/50 rounded-lg px-3 py-2">
              <div>
                <span className="text-red-300 font-mono text-xs">{t.topic}</span>
                <span className="text-red-400 text-xs ml-2">({t.count})</span>
                {t.newest && (
                  <span className="text-red-500/70 text-xs ml-2">
                    latest: {new Date(t.newest).toLocaleString()}
                  </span>
                )}
              </div>
              <button
                onClick={() => resolveMutation.mutate(t.topic)}
                disabled={resolveMutation.isPending}
                className="px-2 py-1 text-xs bg-red-800/50 text-red-300 rounded hover:bg-red-700/50 disabled:opacity-50 transition-all"
              >
                {resolveMutation.isPending ? '...' : 'Resolve'}
              </button>
            </div>
          ))}
      </div>
    </div>
  )
}

function roleEmoji(role: string): string {
  const map: Record<string, string> = {
    ceo: '👔',
    engineer: '💻',
    analyst: '🔍',
    writer: '✍️',
    qa: '🛡️',
    prompt_creator: '🧪',
  }
  return map[role] || '🤖'
}
