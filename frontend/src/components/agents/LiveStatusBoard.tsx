import { useMemo, useEffect, useState } from 'react'
import {
  Activity,
  Brain,
  CheckCircle2,
  Clock,
  Cpu,
  AlertTriangle,
  Pause,
  Wrench,
} from 'lucide-react'
import { useAgents } from '@/hooks/useAgents'
import { useTasks } from '@/hooks/useTasks'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/ui/empty-state'
import { useAgentEventStore, type AgentLifecycleState } from '@/ws/agentEventStore'
import type { AgentInfo } from '@/types'
import { cn } from '@/lib/utils'

const STATE_META: Record<
  AgentLifecycleState,
  { label: string; ring: string; pulse: string; dot: string; icon: typeof Brain }
> = {
  idle: {
    label: 'Idle',
    ring: 'ring-gray-700',
    pulse: '',
    dot: 'bg-gray-500',
    icon: Pause,
  },
  thinking: {
    label: 'Thinking',
    ring: 'ring-blue-500/40',
    pulse: 'animate-pulse',
    dot: 'bg-blue-400',
    icon: Brain,
  },
  calling_tool: {
    label: 'Using tool',
    ring: 'ring-amber-500/40',
    pulse: 'animate-pulse',
    dot: 'bg-amber-400',
    icon: Wrench,
  },
  waiting: {
    label: 'Waiting',
    ring: 'ring-violet-500/40',
    pulse: '',
    dot: 'bg-violet-400',
    icon: Clock,
  },
  failed: {
    label: 'Failed',
    ring: 'ring-red-500/40',
    pulse: '',
    dot: 'bg-red-500',
    icon: AlertTriangle,
  },
}

function relativeSecondsAgo(ts?: number, now?: number): string | null {
  if (!ts) return null
  const seconds = Math.max(0, Math.floor(((now ?? Date.now()) - ts) / 1000))
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  return `${Math.floor(seconds / 3600)}h ago`
}

function AgentTile({
  agent,
  liveState,
  taskInstruction,
  now,
}: {
  agent: AgentInfo
  liveState: AgentLifecycleState
  taskInstruction?: string
  now: number
}) {
  const meta = STATE_META[liveState]
  const Icon = meta.icon
  const lastActivity = useAgentEventStore(
    (s) => s.agents[agent.id]?.last_event_at,
  )

  return (
    <article
      className={cn(
        'rounded-lg bg-gray-900 border border-gray-800 ring-1 transition-all',
        meta.ring,
      )}
      aria-label={`${agent.name} (${meta.label})`}
    >
      <div className="p-4 space-y-3">
        <header className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-3 min-w-0">
            <div
              className={cn(
                'h-9 w-9 rounded-md bg-gray-800 flex items-center justify-center shrink-0',
                meta.pulse,
              )}
              aria-hidden="true"
            >
              <Icon size={16} className="text-gray-200" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-white truncate">{agent.name}</h3>
              <p className="text-[11px] uppercase tracking-wide text-gray-500">
                {agent.role}
              </p>
            </div>
          </div>
          <span
            className={cn(
              'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium border border-gray-700 bg-gray-950',
            )}
          >
            <span className={cn('h-1.5 w-1.5 rounded-full', meta.dot, meta.pulse)} />
            {meta.label}
          </span>
        </header>

        <div className="text-xs text-gray-400 space-y-1">
          <div className="flex items-center gap-1.5">
            <Cpu size={12} className="text-gray-500" aria-hidden="true" />
            <span className="font-mono text-[11px] text-gray-300 truncate">
              {agent.llm_model}
            </span>
          </div>
          {taskInstruction && (
            <p
              className="line-clamp-2 text-gray-300 leading-snug"
              title={taskInstruction}
            >
              {taskInstruction}
            </p>
          )}
        </div>

        <footer className="flex items-center justify-between text-[11px] text-gray-500 pt-2 border-t border-gray-800">
          <span className="inline-flex items-center gap-1">
            <Activity size={11} aria-hidden="true" />
            {relativeSecondsAgo(lastActivity, now) ?? 'no events'}
          </span>
          <span>
            {agent.is_active ? (
              <span className="inline-flex items-center gap-1 text-emerald-400">
                <CheckCircle2 size={11} aria-hidden="true" />
                Online
              </span>
            ) : (
              <span className="text-gray-500">Offline</span>
            )}
          </span>
        </footer>
      </div>
    </article>
  )
}

export function LiveStatusBoard() {
  const { data: agents = [], isLoading } = useAgents()
  const { data: tasks = [] } = useTasks()
  const liveAgents = useAgentEventStore((s) => s.agents)
  const connectionState = useAgentEventStore((s) => s.connectionState)

  // tick once a second so "x seconds ago" stays fresh
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])

  const activeTaskByAgent = useMemo(() => {
    const map = new Map<string, string>()
    for (const t of tasks) {
      if (t.status === 'running' || t.status === 'queued') {
        // Tasks don't currently expose assigned_agent_id in the API response shape.
        // Fall back to the live event store, which records task_id per agent.
      }
      void t
    }
    for (const [agentId, status] of Object.entries(liveAgents)) {
      if (status.task_id) {
        const linked = tasks.find((t) => t.id === status.task_id)
        if (linked) map.set(agentId, linked.instruction)
        else if (status.instruction_snippet) map.set(agentId, status.instruction_snippet)
      }
    }
    return map
  }, [tasks, liveAgents])

  if (isLoading) {
    return (
      <section className="bg-gray-900 rounded-lg p-5 space-y-3">
        <h2 className="text-lg font-semibold text-white">Live agent status</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {[0, 1, 2, 3, 4, 5, 6].map((i) => (
            <Skeleton key={i} className="h-36 w-full" />
          ))}
        </div>
      </section>
    )
  }

  if (agents.length === 0) {
    return (
      <EmptyState
        icon={<Brain size={32} strokeWidth={1.5} />}
        title="No agents registered yet"
        description="Run the seed migration or register at least one agent before submitting tasks."
      />
    )
  }

  const activeCount = Object.values(liveAgents).filter(
    (s) => s.state !== 'idle',
  ).length

  return (
    <section
      className="bg-gray-900 rounded-lg p-5 space-y-4"
      aria-label="Live agent status board"
    >
      <header className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-lg font-semibold text-white">Live agent status</h2>
          <p className="text-xs text-gray-500">
            {activeCount > 0
              ? `${activeCount} agent${activeCount === 1 ? '' : 's'} working right now`
              : 'All agents idle — waiting for the next task'}
          </p>
        </div>
        <span
          className={cn(
            'inline-flex items-center gap-1.5 text-[11px] px-2 py-1 rounded-full border',
            connectionState === 'open'
              ? 'border-emerald-700 text-emerald-300 bg-emerald-900/20'
              : connectionState === 'connecting'
                ? 'border-amber-700 text-amber-300 bg-amber-900/20'
                : 'border-red-700 text-red-300 bg-red-900/20',
          )}
        >
          <span
            className={cn(
              'h-1.5 w-1.5 rounded-full',
              connectionState === 'open'
                ? 'bg-emerald-400 animate-pulse'
                : connectionState === 'connecting'
                  ? 'bg-amber-400 animate-pulse'
                  : 'bg-red-400',
            )}
          />
          {connectionState === 'open'
            ? 'Live'
            : connectionState === 'connecting'
              ? 'Connecting…'
              : 'Disconnected'}
        </span>
      </header>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {agents.map((agent) => {
          const live = liveAgents[agent.id]
          const state: AgentLifecycleState = live?.state ?? 'idle'
          return (
            <AgentTile
              key={agent.id}
              agent={agent}
              liveState={state}
              taskInstruction={activeTaskByAgent.get(agent.id)}
              now={now}
            />
          )
        })}
      </div>
    </section>
  )
}
