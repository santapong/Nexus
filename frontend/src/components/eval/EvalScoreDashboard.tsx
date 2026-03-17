import { useState } from 'react'
import { useEvalScores, useTriggerEvalRun } from '../../hooks/useEval'

const PERIODS = ['7d', '30d', 'all'] as const

export function EvalScoreDashboard() {
  const [period, setPeriod] = useState<string>('7d')
  const { data, isLoading } = useEvalScores(period)
  const evalRun = useTriggerEvalRun()

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <span className="text-2xl">🎯</span> Eval Scores
        </h2>
        <div className="flex items-center gap-3">
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
          <button
            onClick={() => evalRun.mutate()}
            disabled={evalRun.isPending}
            className="px-3 py-1 text-xs bg-indigo-600 text-white rounded-md hover:bg-indigo-500 disabled:opacity-50 transition-all"
          >
            {evalRun.isPending ? 'Running...' : 'Run Eval'}
          </button>
        </div>
      </div>

      {evalRun.data && (
        <div className={`text-xs px-3 py-2 rounded-lg ${
          evalRun.data.triggered
            ? 'bg-green-950/30 border border-green-800/50 text-green-400'
            : 'bg-red-950/30 border border-red-800/50 text-red-400'
        }`}>
          {evalRun.data.message}
        </div>
      )}

      {isLoading ? (
        <div className="text-gray-500 text-sm animate-pulse">Loading eval scores...</div>
      ) : data && data.total_evaluated > 0 ? (
        <>
          {/* Summary */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Tasks Evaluated</div>
              <div className="text-2xl font-bold text-white">{data.total_evaluated}</div>
            </div>
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Mean Score</div>
              <div className={`text-2xl font-bold ${scoreColor(data.mean_score)}`}>
                {(data.mean_score * 100).toFixed(1)}%
              </div>
            </div>
          </div>

          {/* By Role */}
          {data.by_role.length > 0 && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-800">
                <h3 className="text-sm font-semibold text-gray-300">Scores by Role</h3>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 text-xs uppercase tracking-wider">
                    <th className="text-left px-4 py-2">Role</th>
                    <th className="text-right px-4 py-2">Evaluated</th>
                    <th className="text-right px-4 py-2">Mean Score</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_role.map((r) => (
                    <tr key={r.role} className="border-t border-gray-800 hover:bg-gray-800/50">
                      <td className="px-4 py-3 text-white font-medium capitalize">{r.role}</td>
                      <td className="text-right px-4 py-3 text-gray-300">{r.count}</td>
                      <td className={`text-right px-4 py-3 font-medium ${scoreColor(r.mean_score)}`}>
                        {(r.mean_score * 100).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Recent Scores */}
          {data.recent.length > 0 && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-800">
                <h3 className="text-sm font-semibold text-gray-300">Recent Evaluations</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-gray-500 text-xs uppercase tracking-wider">
                      <th className="text-left px-4 py-2">Task</th>
                      <th className="text-right px-4 py-2">Overall</th>
                      <th className="text-right px-4 py-2">Relevance</th>
                      <th className="text-right px-4 py-2">Complete</th>
                      <th className="text-right px-4 py-2">Accuracy</th>
                      <th className="text-right px-4 py-2">Format</th>
                      <th className="text-right px-4 py-2">Judge</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent.map((entry) => (
                      <tr key={entry.task_id + entry.created_at} className="border-t border-gray-800 hover:bg-gray-800/50">
                        <td className="px-4 py-2 text-gray-400 font-mono text-xs">
                          {entry.task_id.slice(0, 8)}...
                        </td>
                        <td className={`text-right px-4 py-2 font-medium ${scoreColor(entry.overall_score)}`}>
                          {(entry.overall_score * 100).toFixed(0)}%
                        </td>
                        <td className="text-right px-4 py-2 text-gray-300">
                          {entry.relevance != null ? `${(entry.relevance * 100).toFixed(0)}%` : '—'}
                        </td>
                        <td className="text-right px-4 py-2 text-gray-300">
                          {entry.completeness != null ? `${(entry.completeness * 100).toFixed(0)}%` : '—'}
                        </td>
                        <td className="text-right px-4 py-2 text-gray-300">
                          {entry.accuracy != null ? `${(entry.accuracy * 100).toFixed(0)}%` : '—'}
                        </td>
                        <td className="text-right px-4 py-2 text-gray-300">
                          {entry.formatting != null ? `${(entry.formatting * 100).toFixed(0)}%` : '—'}
                        </td>
                        <td className="text-right px-4 py-2 text-gray-500 font-mono text-xs">
                          {entry.judge_model || '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="text-gray-500 text-sm">
          No eval scores yet. Run an eval to score recent task outputs.
        </div>
      )}
    </div>
  )
}

function scoreColor(score: number): string {
  if (score >= 0.8) return 'text-green-400'
  if (score >= 0.6) return 'text-yellow-400'
  return 'text-red-400'
}
