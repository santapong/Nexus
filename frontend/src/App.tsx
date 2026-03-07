import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

const API_URL = import.meta.env.VITE_API_URL || ''

// ─── Types ────────────────────────────────────────────────────────────────────

interface HealthCheck {
  status: string
  checks: Record<string, string>
}

interface Task {
  id: string
  trace_id: string
  instruction: string
  status: string
  source: string
  tokens_used: number
  output: Record<string, unknown> | null
  error: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

interface Approval {
  id: string
  task_id: string
  tool_name: string
  action_description: string
  status: string
  requested_at: string
}

// ─── API helpers ──────────────────────────────────────────────────────────────

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

// ─── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    queued: 'bg-gray-600 text-gray-100',
    running: 'bg-blue-600 text-blue-100',
    completed: 'bg-green-700 text-green-100',
    failed: 'bg-red-700 text-red-100',
    paused: 'bg-yellow-700 text-yellow-100',
    escalated: 'bg-orange-700 text-orange-100',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] ?? 'bg-gray-700 text-gray-200'}`}>
      {status}
    </span>
  )
}

// ─── System Health ────────────────────────────────────────────────────────────

function HealthPanel() {
  const { data: health, isLoading, error } = useQuery<HealthCheck>({
    queryKey: ['health'],
    queryFn: () => apiFetch('/health'),
    refetchInterval: 10_000,
  })

  return (
    <section className="bg-gray-900 rounded-lg p-5">
      <h2 className="text-lg font-semibold mb-3 text-white">System Health</h2>
      {isLoading && <p className="text-gray-400 text-sm">Checking…</p>}
      {error && <p className="text-red-400 text-sm">Connection failed</p>}
      {health && (
        <div>
          <p className={`text-sm font-medium mb-2 ${health.status === 'healthy' ? 'text-green-400' : 'text-yellow-400'}`}>
            {health.status}
          </p>
          <ul className="space-y-1">
            {Object.entries(health.checks).map(([name, st]) => (
              <li key={name} className="flex justify-between text-sm">
                <span className="text-gray-400">{name}</span>
                <span className={st === 'ok' ? 'text-green-400' : 'text-red-400'}>{st}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

// ─── Submit Task ──────────────────────────────────────────────────────────────

function SubmitTaskPanel({ onSubmitted }: { onSubmitted: () => void }) {
  const [instruction, setInstruction] = useState('')

  const mutation = useMutation({
    mutationFn: () =>
      apiFetch<{ task_id: string; status: string }>('/tasks', {
        method: 'POST',
        body: JSON.stringify({ instruction }),
      }),
    onSuccess: () => {
      setInstruction('')
      onSubmitted()
    },
  })

  return (
    <section className="bg-gray-900 rounded-lg p-5">
      <h2 className="text-lg font-semibold mb-3 text-white">Submit Task</h2>
      <textarea
        className="w-full bg-gray-800 text-gray-100 rounded p-3 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-blue-500"
        rows={4}
        placeholder="Describe the task for the Engineer agent…"
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
      />
      <div className="flex items-center gap-3 mt-3">
        <button
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          onClick={() => mutation.mutate()}
          disabled={!instruction.trim() || mutation.isPending}
        >
          {mutation.isPending ? 'Submitting…' : 'Submit'}
        </button>
        {mutation.isError && (
          <span className="text-red-400 text-sm">Failed to submit task</span>
        )}
        {mutation.isSuccess && (
          <span className="text-green-400 text-sm">Task queued!</span>
        )}
      </div>
    </section>
  )
}

// ─── Task List ────────────────────────────────────────────────────────────────

function TaskRow({ task }: { task: Task }) {
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
        <span className="text-gray-500 text-xs mt-1">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div className="border-t border-gray-700 p-4 space-y-3">
          <div className="text-xs text-gray-500">Task ID: {task.id}</div>

          {task.output && (
            <div>
              <p className="text-xs text-gray-400 mb-1 font-medium uppercase tracking-wide">Output</p>
              <pre className="bg-gray-950 text-green-300 text-xs p-3 rounded overflow-auto max-h-96 whitespace-pre-wrap">
                {typeof task.output.result === 'string'
                  ? task.output.result
                  : JSON.stringify(task.output, null, 2)}
              </pre>
            </div>
          )}

          {task.error && (
            <div>
              <p className="text-xs text-gray-400 mb-1 font-medium uppercase tracking-wide">Error</p>
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

function TaskListPanel({ refreshSignal }: { refreshSignal: number }) {
  const queryClient = useQueryClient()

  const { data: tasks = [], isLoading } = useQuery<Task[]>({
    queryKey: ['tasks', refreshSignal],
    queryFn: () => apiFetch('/tasks?limit=50'),
    refetchInterval: 3_000,
  })

  // Refresh when parent triggers (e.g. new task submitted)
  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: ['tasks'] })
  }, [refreshSignal, queryClient])

  return (
    <section className="bg-gray-900 rounded-lg p-5">
      <h2 className="text-lg font-semibold mb-3 text-white">
        Tasks
        <span className="ml-2 text-sm text-gray-500 font-normal">({tasks.length})</span>
      </h2>
      {isLoading && <p className="text-gray-400 text-sm">Loading…</p>}
      {!isLoading && tasks.length === 0 && (
        <p className="text-gray-500 text-sm">No tasks yet. Submit one above.</p>
      )}
      <div className="space-y-2">
        {tasks.map((t) => (
          <TaskRow key={t.id} task={t} />
        ))}
      </div>
    </section>
  )
}

// ─── Approval Queue ───────────────────────────────────────────────────────────

function ApprovalPanel() {
  const queryClient = useQueryClient()

  const { data: approvals = [] } = useQuery<Approval[]>({
    queryKey: ['approvals'],
    queryFn: () => apiFetch('/approvals'),
    refetchInterval: 5_000,
  })

  const pending = approvals.filter((a) => a.status === 'pending')

  const approveMutation = useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/approvals/${id}/approve`, {
        method: 'POST',
        body: JSON.stringify({ resolved_by: 'human' }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['approvals'] }),
  })

  const rejectMutation = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      apiFetch(`/approvals/${id}/reject`, {
        method: 'POST',
        body: JSON.stringify({ resolved_by: 'human', reason }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['approvals'] }),
  })

  if (pending.length === 0) return null

  return (
    <section className="bg-yellow-950 border border-yellow-800 rounded-lg p-5">
      <h2 className="text-lg font-semibold mb-3 text-yellow-300">
        Approvals Needed ({pending.length})
      </h2>
      <div className="space-y-3">
        {pending.map((a) => (
          <div key={a.id} className="bg-gray-900 rounded p-4 space-y-2">
            <p className="text-sm text-gray-200">
              <span className="font-medium text-yellow-400">{a.tool_name}</span>
              {' — '}
              {a.action_description}
            </p>
            <p className="text-xs text-gray-500">Task: {a.task_id}</p>
            <div className="flex gap-2 mt-2">
              <button
                className="px-3 py-1 bg-green-700 hover:bg-green-600 text-white rounded text-sm disabled:opacity-50"
                onClick={() => approveMutation.mutate(a.id)}
                disabled={approveMutation.isPending}
              >
                Approve
              </button>
              <button
                className="px-3 py-1 bg-red-700 hover:bg-red-600 text-white rounded text-sm disabled:opacity-50"
                onClick={() => rejectMutation.mutate({ id: a.id, reason: 'Rejected by human' })}
                disabled={rejectMutation.isPending}
              >
                Reject
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

// ─── WebSocket live updates ───────────────────────────────────────────────────

function useAgentWebSocket(onEvent: (event: unknown) => void) {
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  useEffect(() => {
    const wsUrl = (API_URL || window.location.origin)
      .replace(/^http/, 'ws')
      .replace(/\/$/, '')
    const ws = new WebSocket(`${wsUrl}/ws/agents`)

    ws.onmessage = (msg) => {
      try {
        const data: unknown = JSON.parse(msg.data as string)
        onEventRef.current(data)
      } catch {
        // ignore malformed frames
      }
    }

    ws.onerror = () => {
      // silently reconnect on next render cycle
    }

    return () => ws.close()
  }, [])
}

// ─── App ──────────────────────────────────────────────────────────────────────

function App() {
  const queryClient = useQueryClient()
  const [submitSignal, setSubmitSignal] = useState(0)

  // Invalidate task list on any live agent event
  useAgentWebSocket(() => {
    void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    void queryClient.invalidateQueries({ queryKey: ['approvals'] })
  })

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 p-6">
      <header className="mb-6">
        <h1 className="text-3xl font-bold text-white tracking-tight">NEXUS</h1>
        <p className="text-gray-500 text-sm mt-1">Agentic AI Company as a Service</p>
      </header>

      <div className="max-w-3xl mx-auto space-y-4">
        <ApprovalPanel />

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="md:col-span-1">
            <HealthPanel />
          </div>
          <div className="md:col-span-2">
            <SubmitTaskPanel onSubmitted={() => setSubmitSignal((v) => v + 1)} />
          </div>
        </div>

        <TaskListPanel refreshSignal={submitSignal} />
      </div>
    </div>
  )
}

export default App
