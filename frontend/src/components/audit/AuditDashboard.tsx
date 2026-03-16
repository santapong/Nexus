import { useState } from 'react'
import { useAuditEvents } from '../../hooks/useAudit'
import type { AuditEvent } from '../../types'

const EVENT_TYPE_COLORS: Record<string, string> = {
  task_completed: 'bg-green-100 text-green-800',
  task_received: 'bg-blue-100 text-blue-800',
  task_failed: 'bg-red-100 text-red-800',
  budget_exceeded: 'bg-yellow-100 text-yellow-800',
  tool_call_limit_reached: 'bg-yellow-100 text-yellow-800',
  approval_requested: 'bg-purple-100 text-purple-800',
  approval_resolved: 'bg-purple-100 text-purple-800',
  heartbeat_silence: 'bg-red-100 text-red-800',
  prompt_activated: 'bg-indigo-100 text-indigo-800',
  prompt_created: 'bg-indigo-100 text-indigo-800',
}

const EVENT_TYPES = [
  'task_received',
  'task_completed',
  'task_failed',
  'budget_exceeded',
  'tool_call_limit_reached',
  'approval_requested',
  'approval_resolved',
  'heartbeat_silence',
  'prompt_activated',
  'prompt_created',
]

export function AuditDashboard() {
  const [eventType, setEventType] = useState<string>('')
  const [page, setPage] = useState(0)
  const [expanded, setExpanded] = useState<string | null>(null)
  const limit = 20

  const { data: events, isLoading, error } = useAuditEvents({
    event_type: eventType || undefined,
    limit,
    offset: page * limit,
  })

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h2 className="text-lg font-semibold mb-4">Audit Log</h2>

      {/* Filters */}
      <div className="flex gap-4 mb-4">
        <select
          className="border rounded px-2 py-1 text-sm"
          value={eventType}
          onChange={(e) => {
            setEventType(e.target.value)
            setPage(0)
          }}
        >
          <option value="">All event types</option>
          {EVENT_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>

      {/* Loading / Error */}
      {isLoading && (
        <p className="text-gray-500 text-sm">Loading audit events...</p>
      )}
      {error && (
        <p className="text-red-500 text-sm">
          Error loading audit log: {String(error)}
        </p>
      )}

      {/* Event list */}
      {events && events.length > 0 ? (
        <div className="space-y-2">
          {events.map((event: AuditEvent) => (
            <div
              key={event.id}
              className="border rounded p-3 hover:bg-gray-50 cursor-pointer"
              onClick={() =>
                setExpanded(expanded === event.id ? null : event.id)
              }
            >
              <div className="flex items-center gap-2 text-sm">
                <span
                  className={`px-2 py-0.5 rounded text-xs font-medium ${
                    EVENT_TYPE_COLORS[event.event_type] ||
                    'bg-gray-100 text-gray-800'
                  }`}
                >
                  {event.event_type}
                </span>
                <span className="text-gray-500 font-mono text-xs">
                  {event.agent_id}
                </span>
                <span className="text-gray-400 text-xs ml-auto">
                  {new Date(event.created_at).toLocaleString()}
                </span>
              </div>

              <div className="text-xs text-gray-500 mt-1 font-mono">
                task: {event.task_id.slice(0, 8)}...
              </div>

              {/* Expanded detail */}
              {expanded === event.id && (
                <pre className="mt-2 bg-gray-50 p-2 rounded text-xs overflow-auto max-h-48">
                  {JSON.stringify(event.event_data, null, 2)}
                </pre>
              )}
            </div>
          ))}
        </div>
      ) : (
        !isLoading && (
          <p className="text-gray-500 text-sm">No audit events found.</p>
        )
      )}

      {/* Pagination */}
      <div className="flex gap-2 mt-4">
        <button
          className="px-3 py-1 text-sm border rounded disabled:opacity-50"
          disabled={page === 0}
          onClick={() => setPage(page - 1)}
        >
          Previous
        </button>
        <span className="px-3 py-1 text-sm text-gray-500">
          Page {page + 1}
        </span>
        <button
          className="px-3 py-1 text-sm border rounded disabled:opacity-50"
          disabled={!events || events.length < limit}
          onClick={() => setPage(page + 1)}
        >
          Next
        </button>
      </div>
    </div>
  )
}
