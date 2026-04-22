import { useState } from 'react'
import { useTaskReplay } from '../../hooks/useAnalytics'
import { StatusBadge } from '../dashboard/StatusBadge'
import { TaskFeedbackModal } from './TaskFeedbackModal'

export function TaskReplayView({
  taskId,
  onClose,
}: {
  taskId: string
  onClose: () => void
}) {
  const { data: replay, isLoading, error } = useTaskReplay(taskId)
  const [activeTab, setActiveTab] = useState<'timeline' | 'llm' | 'subtasks'>('timeline')
  const [feedbackOpen, setFeedbackOpen] = useState(false)

  if (isLoading) {
    return (
      <div className="bg-gray-900 border border-gray-700 rounded-lg p-4 animate-pulse">
        <div className="text-gray-500 text-sm">Loading task replay...</div>
      </div>
    )
  }

  if (error || !replay) {
    return (
      <div className="bg-gray-900 border border-red-800/50 rounded-lg p-4">
        <div className="text-red-400 text-sm">Failed to load replay data</div>
        <button
          onClick={onClose}
          className="text-xs text-gray-500 hover:text-white mt-2 transition-colors"
        >
          Close
        </button>
      </div>
    )
  }

  const isCompleted = replay.task.status === 'completed'

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700 bg-gray-800/50">
        <div className="flex items-center gap-3">
          <span className="text-lg">🔄</span>
          <div>
            <div className="text-sm font-semibold text-white">Task Replay</div>
            <div className="text-xs text-gray-500">
              {replay.total_episodes} episodes · {replay.total_llm_calls} LLM calls
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isCompleted && (
            <button
              onClick={() => setFeedbackOpen(true)}
              className="rounded-md border border-indigo-700 bg-indigo-600/30 px-2.5 py-1 text-xs font-medium text-indigo-200 transition-colors hover:bg-indigo-600/50"
            >
              🗣️ Rate task
            </button>
          )}
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-white text-sm transition-colors"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-700">
        {(['timeline', 'llm', 'subtasks'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-xs font-medium transition-colors ${
              activeTab === tab
                ? 'text-indigo-400 border-b-2 border-indigo-400'
                : 'text-gray-500 hover:text-white'
            }`}
          >
            {tab === 'timeline' ? '📝 Episodes' : tab === 'llm' ? '🤖 LLM Calls' : '🔀 Subtasks'}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="p-4 max-h-96 overflow-y-auto">
        {activeTab === 'timeline' && (
          <div className="space-y-3">
            {replay.episodes.length === 0 ? (
              <div className="text-gray-500 text-sm">No episodic memory recorded for this task.</div>
            ) : (
              replay.episodes.map((ep, i) => (
                <div key={i} className="border-l-2 border-indigo-600 pl-4 space-y-1">
                  <div className="flex items-center gap-2">
                    <StatusBadge status={ep.outcome} />
                    <span className="text-xs text-gray-400">{new Date(ep.created_at).toLocaleString()}</span>
                  </div>
                  <p className="text-sm text-gray-200">{ep.summary}</p>
                  {ep.tools_used && ep.tools_used.length > 0 && (
                    <div className="flex gap-1 flex-wrap">
                      {ep.tools_used.map((tool) => (
                        <span key={tool} className="text-[10px] bg-gray-800 text-gray-400 px-1.5 py-0.5 rounded">
                          🔧 {tool}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="text-xs text-gray-500">
                    {ep.tokens_used && `${ep.tokens_used.toLocaleString()} tokens`}
                    {ep.duration_seconds && ` · ${ep.duration_seconds}s`}
                    {` · importance: ${ep.importance_score}`}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'llm' && (
          <div className="space-y-2">
            {replay.llm_calls.length === 0 ? (
              <div className="text-gray-500 text-sm">No LLM calls recorded for this task.</div>
            ) : (
              replay.llm_calls.map((call, i) => (
                <div key={i} className="bg-gray-800 rounded-lg p-3 flex items-center justify-between">
                  <div>
                    <div className="text-xs font-mono text-indigo-300">{call.model_name}</div>
                    <div className="text-xs text-gray-500 mt-0.5">
                      {new Date(call.created_at).toLocaleString()}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-gray-300">
                      {call.input_tokens.toLocaleString()} → {call.output_tokens.toLocaleString()} tok
                    </div>
                    <div className="text-xs text-green-400">
                      ${call.cost_usd.toFixed(6)}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'subtasks' && (
          <div className="space-y-3">
            {replay.subtask_episodes.length === 0 && replay.subtask_llm_calls.length === 0 ? (
              <div className="text-gray-500 text-sm">No subtask data — this may be a single-agent task.</div>
            ) : (
              <>
                {replay.subtask_episodes.map((ep, i) => (
                  <div key={`ep-${i}`} className="border-l-2 border-purple-600 pl-4 space-y-1">
                    <div className="flex items-center gap-2">
                      <StatusBadge status={ep.outcome} />
                      <span className="text-[10px] font-mono text-gray-500">subtask:{ep.subtask_id.slice(0, 8)}</span>
                    </div>
                    <p className="text-sm text-gray-200">{ep.summary}</p>
                  </div>
                ))}
                {replay.subtask_llm_calls.map((call, i) => (
                  <div key={`llm-${i}`} className="bg-gray-800 rounded-lg p-3 flex items-center justify-between">
                    <div>
                      <div className="text-xs font-mono text-purple-300">{call.model_name}</div>
                      <div className="text-[10px] text-gray-500">subtask:{call.subtask_id.slice(0, 8)}</div>
                    </div>
                    <div className="text-right text-xs text-gray-300">
                      {call.input_tokens.toLocaleString()} + {call.output_tokens.toLocaleString()} tok · ${call.cost_usd.toFixed(6)}
                    </div>
                  </div>
                ))}
              </>
            )}
          </div>
        )}
      </div>

      {feedbackOpen && (
        <TaskFeedbackModal taskId={taskId} onClose={() => setFeedbackOpen(false)} />
      )}
    </div>
  )
}
