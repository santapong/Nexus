import { useState } from 'react';
import { useTaskTrace } from '../../hooks/useTaskTrace';
import { StatusBadge } from '../dashboard/StatusBadge';

interface TaskTraceViewProps {
  taskId: string;
  onClose: () => void;
}

export function TaskTraceView({ taskId, onClose }: TaskTraceViewProps) {
  const { data: trace, isLoading, error } = useTaskTrace(taskId);
  const [expandedSubtask, setExpandedSubtask] = useState<string | null>(null);

  if (isLoading) {
    return (
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-white">Task Trace</h3>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors"
          >
            ✕
          </button>
        </div>
        <div className="text-gray-400 animate-pulse">Loading trace...</div>
      </div>
    );
  }

  if (error || !trace) {
    return (
      <div className="bg-gray-800 rounded-lg p-4 border border-red-700">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-white">Task Trace</h3>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors"
          >
            ✕
          </button>
        </div>
        <div className="text-red-400">Failed to load trace</div>
      </div>
    );
  }

  const progressPct = trace.total_subtasks > 0
    ? Math.round((trace.completed_subtasks / trace.total_subtasks) * 100)
    : 0;

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-gray-700">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-semibold text-white">Task Trace</h3>
          <StatusBadge status={trace.parent.status} />
          <span className="text-sm text-gray-400">
            {trace.completed_subtasks}/{trace.total_subtasks} subtasks
          </span>
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-white transition-colors text-lg"
        >
          ✕
        </button>
      </div>

      {/* Progress bar */}
      {trace.total_subtasks > 0 && (
        <div className="px-4 pt-3">
          <div className="w-full bg-gray-700 rounded-full h-2">
            <div
              className="bg-green-500 h-2 rounded-full transition-all duration-500"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <div className="text-xs text-gray-500 mt-1">{progressPct}% complete</div>
        </div>
      )}

      {/* Parent task */}
      <div className="p-4 border-b border-gray-700">
        <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Parent Task</div>
        <div className="text-sm text-gray-200">{trace.parent.instruction}</div>
        <div className="flex items-center gap-3 mt-2 text-xs text-gray-500">
          <span>ID: {trace.parent.id.slice(0, 8)}...</span>
          <span>Tokens: {trace.parent.tokens_used}</span>
          {trace.parent.created_at && (
            <span>Created: {new Date(trace.parent.created_at).toLocaleTimeString()}</span>
          )}
        </div>
      </div>

      {/* Subtasks */}
      {trace.subtasks.length > 0 && (
        <div className="divide-y divide-gray-700">
          {trace.subtasks.map((sub, idx) => (
            <div key={sub.id} className="p-4 hover:bg-gray-750 transition-colors">
              <div
                className="flex items-center justify-between cursor-pointer"
                onClick={() => setExpandedSubtask(
                  expandedSubtask === sub.id ? null : sub.id
                )}
              >
                <div className="flex items-center gap-3">
                  <span className="text-xs text-gray-500 font-mono w-6">
                    #{idx + 1}
                  </span>
                  <StatusBadge status={sub.status} />
                  <span className="text-sm text-gray-300 truncate max-w-md">
                    {sub.instruction}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-xs text-gray-500">
                  <span>{sub.tokens_used} tokens</span>
                  <span className="text-gray-600">
                    {expandedSubtask === sub.id ? '▼' : '▶'}
                  </span>
                </div>
              </div>

              {/* Expanded details */}
              {expandedSubtask === sub.id && (
                <div className="mt-3 ml-9 space-y-2">
                  <div className="text-sm text-gray-300">
                    <span className="text-gray-500">Full instruction: </span>
                    {sub.instruction}
                  </div>
                  {sub.output && (
                    <div className="bg-gray-900 rounded p-3 text-xs text-gray-400 font-mono max-h-48 overflow-auto">
                      <div className="text-gray-500 mb-1">Output:</div>
                      {JSON.stringify(sub.output, null, 2)}
                    </div>
                  )}
                  {sub.error && (
                    <div className="bg-red-900/30 border border-red-800 rounded p-3 text-xs text-red-300">
                      <div className="text-red-400 mb-1">Error:</div>
                      {sub.error}
                    </div>
                  )}
                  <div className="flex items-center gap-4 text-xs text-gray-500">
                    <span>ID: {sub.id.slice(0, 8)}...</span>
                    {sub.started_at && (
                      <span>Started: {new Date(sub.started_at).toLocaleTimeString()}</span>
                    )}
                    {sub.completed_at && (
                      <span>Completed: {new Date(sub.completed_at).toLocaleTimeString()}</span>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* No subtasks */}
      {trace.subtasks.length === 0 && (
        <div className="p-4 text-sm text-gray-500">
          No subtasks — this task was handled directly.
        </div>
      )}
    </div>
  );
}
