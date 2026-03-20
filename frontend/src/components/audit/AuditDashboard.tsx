import { useState } from 'react'
import { useAuditEvents } from '../../hooks/useAudit'
import type { AuditEvent } from '../../types'
import { Select } from '../ui/select'
import { Button } from '../ui/button'
import { Skeleton } from '../ui/skeleton'

const EVENT_TYPE_COLORS: Record<string, string> = {
  task_completed: 'bg-green-700 text-green-100',
  task_received: 'bg-blue-700 text-blue-100',
  task_failed: 'bg-red-700 text-red-100',
  budget_exceeded: 'bg-yellow-700 text-yellow-100',
  tool_call_limit_reached: 'bg-yellow-700 text-yellow-100',
  approval_requested: 'bg-purple-700 text-purple-100',
  approval_resolved: 'bg-purple-700 text-purple-100',
  heartbeat_silence: 'bg-red-700 text-red-100',
  prompt_activated: 'bg-indigo-700 text-indigo-100',
  prompt_created: 'bg-indigo-700 text-indigo-100',
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
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-5">
      <h2 className="text-lg font-semibold mb-4 text-white">Audit Log</h2>

      {/* Filters */}
      <div className="flex gap-4 mb-4">
        <Select
          value={eventType}
          onChange={(e) => {
            setEventType(e.target.value)
            setPage(0)
          }}
          className="w-52"
        >
          <option value="">All event types</option>
          {EVENT_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </Select>
      </div>

      {/* Loading / Error */}
      {isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      )}
      {error && (
        <p className="text-red-400 text-sm">
          Error loading audit log: {String(error)}
        </p>
      )}

      {/* Event list */}
      {events && events.length > 0 ? (
        <div className="space-y-2">
          {events.map((event: AuditEvent) => (
            <div
              key={event.id}
              className="border border-gray-700 rounded-lg p-3 hover:bg-gray-800/50 cursor-pointer transition-colors"
              onClick={() =>
                setExpanded(expanded === event.id ? null : event.id)
              }
            >
              <div className="flex items-center gap-2 text-sm">
                <span
                  className={`px-2 py-0.5 rounded text-xs font-medium ${
                    EVENT_TYPE_COLORS[event.event_type] ||
                    'bg-gray-700 text-gray-200'
                  }`}
                >
                  {event.event_type}
                </span>
                <span className="text-gray-400 font-mono text-xs">
                  {event.agent_id}
                </span>
                <span className="text-gray-500 text-xs ml-auto">
                  {new Date(event.created_at).toLocaleString()}
                </span>
              </div>

              <div className="text-xs text-gray-500 mt-1 font-mono">
                task: {event.task_id.slice(0, 8)}...
              </div>

              {/* Expanded detail */}
              {expanded === event.id && (
                <pre className="mt-2 bg-gray-950 p-3 rounded text-xs overflow-auto max-h-48 text-gray-300 border border-gray-800">
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
      <div className="flex items-center gap-2 mt-4">
        <Button
          variant="outline"
          size="sm"
          disabled={page === 0}
          onClick={() => setPage(page - 1)}
        >
          Previous
        </Button>
        <span className="px-3 py-1 text-sm text-gray-500">
          Page {page + 1}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={!events || events.length < limit}
          onClick={() => setPage(page + 1)}
        >
          Next
        </Button>
      </div>
    </div>
  )
}
