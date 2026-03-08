import { useState } from 'react'
import type { Task } from '../../types'
import { StatusBadge } from '../dashboard/StatusBadge'

export function TaskRow({ task }: { task: Task }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="border border-gray-700 rounded-lg overflow-hidden">
      <button
        className="w-full flex items-start gap-3 p-4 text-left hover:bg-gray-800 transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <StatusBadge status={task.status} />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-gray-200 truncate">{task.instruction}</p>
          <p className="text-xs text-gray-500 mt-1">
            {new Date(task.created_at).toLocaleString()}
            {task.tokens_used > 0 && ` · ${task.tokens_used.toLocaleString()} tokens`}
          </p>
        </div>
        <span className="text-gray-500 text-xs mt-1">{expanded ? '\u25B2' : '\u25BC'}</span>
      </button>

      {expanded && (
        <div className="border-t border-gray-700 p-4 space-y-3">
          <div className="text-xs text-gray-500">Task ID: {task.id}</div>

          {task.output && (
            <div>
              <p className="text-xs text-gray-400 mb-1 font-medium uppercase tracking-wide">
                Output
              </p>
              <pre className="bg-gray-950 text-green-300 text-xs p-3 rounded overflow-auto max-h-96 whitespace-pre-wrap">
                {typeof task.output.result === 'string'
                  ? task.output.result
                  : JSON.stringify(task.output, null, 2)}
              </pre>
            </div>
          )}

          {task.error && (
            <div>
              <p className="text-xs text-gray-400 mb-1 font-medium uppercase tracking-wide">
                Error
              </p>
              <pre className="bg-gray-950 text-red-300 text-xs p-3 rounded overflow-auto max-h-40 whitespace-pre-wrap">
                {task.error}
              </pre>
            </div>
          )}

          {task.completed_at && (
            <p className="text-xs text-gray-500">
              Completed: {new Date(task.completed_at).toLocaleString()}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
