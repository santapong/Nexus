import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  Brain,
  CheckCircle2,
  CircleDot,
  Database,
  MessagesSquare,
  Pause,
  Play,
  Trash2,
  Wrench,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { useAgentEventStore, type ThinkingEntry } from '@/ws/agentEventStore'
import { cn } from '@/lib/utils'

const TONE_STYLES: Record<ThinkingEntry['tone'], string> = {
  info: 'border-l-gray-600 text-gray-300',
  thinking: 'border-l-blue-500 text-blue-200',
  tool: 'border-l-amber-500 text-amber-200',
  success: 'border-l-emerald-500 text-emerald-200',
  warn: 'border-l-yellow-500 text-yellow-200',
  error: 'border-l-red-500 text-red-200',
}

function iconForKind(kind: ThinkingEntry['kind']) {
  switch (kind) {
    case 'task_started':
    case 'state_change':
      return CircleDot
    case 'task_completed':
      return CheckCircle2
    case 'task_failed':
      return AlertCircle
    case 'llm_call':
      return Brain
    case 'tool_call':
    case 'tool_result':
      return Wrench
    case 'memory_read':
    case 'memory_write':
      return Database
    case 'meeting_message':
    case 'meeting_convergence':
      return MessagesSquare
    default:
      return CircleDot
  }
}

function formatTime(ts: number): string {
  const d = new Date(ts)
  return d.toLocaleTimeString(undefined, {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function shortId(id?: string): string {
  if (!id) return ''
  return id.length > 8 ? `${id.slice(0, 6)}…` : id
}

interface ThinkingStreamProps {
  /** Optional task filter — when set, only events for that task are shown. */
  taskId?: string
  className?: string
  title?: string
  subtitle?: string
  maxHeight?: string
}

export function ThinkingStream({
  taskId,
  className,
  title = 'Agent thinking stream',
  subtitle,
  maxHeight = '24rem',
}: ThinkingStreamProps) {
  const allEntries = useAgentEventStore((s) => s.thinking)
  const clearThinking = useAgentEventStore((s) => s.clearThinking)
  const [paused, setPaused] = useState(false)
  const [snapshot, setSnapshot] = useState<ThinkingEntry[]>([])
  const containerRef = useRef<HTMLDivElement | null>(null)
  const stickToTopRef = useRef(true)

  const entries = useMemo(() => {
    const stream = paused ? snapshot : allEntries
    return taskId ? stream.filter((e) => e.task_id === taskId) : stream
  }, [allEntries, snapshot, paused, taskId])

  // capture snapshot when paused
  useEffect(() => {
    if (paused) setSnapshot(allEntries)
  }, [paused, allEntries])

  // auto-scroll to top (newest) when not paused and user is near top
  useEffect(() => {
    if (paused || !containerRef.current) return
    if (stickToTopRef.current) {
      containerRef.current.scrollTop = 0
    }
  }, [entries, paused])

  function onScroll() {
    if (!containerRef.current) return
    stickToTopRef.current = containerRef.current.scrollTop < 24
  }

  return (
    <section
      className={cn('bg-gray-900 rounded-lg border border-gray-800 flex flex-col', className)}
      aria-label={title}
    >
      <header className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          <p className="text-[11px] text-gray-500 truncate">
            {subtitle ??
              (taskId
                ? `Filter: task ${shortId(taskId)}`
                : 'Live activity from every agent')}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setPaused((v) => !v)}
            aria-label={paused ? 'Resume live updates' : 'Pause live updates'}
          >
            {paused ? <Play size={13} /> : <Pause size={13} />}
            {paused ? 'Resume' : 'Pause'}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => clearThinking()}
            aria-label="Clear stream"
          >
            <Trash2 size={13} />
            Clear
          </Button>
        </div>
      </header>

      <div
        ref={containerRef}
        onScroll={onScroll}
        className="overflow-y-auto px-2 py-2 font-mono"
        style={{ maxHeight }}
      >
        {entries.length === 0 ? (
          <div className="px-2 py-6">
            <EmptyState
              icon={<Brain size={28} strokeWidth={1.5} />}
              title="Stream is quiet"
              description={
                taskId
                  ? 'No live activity for this task yet. Submit a task or wait for the next event.'
                  : 'No live activity yet. Submit a task and watch the agents work.'
              }
            />
          </div>
        ) : (
          <ul className="space-y-1">
            {entries.map((entry) => {
              const Icon = iconForKind(entry.kind)
              return (
                <li
                  key={entry.id}
                  className={cn(
                    'border-l-2 pl-3 pr-2 py-1.5 rounded-r bg-gray-950/40 hover:bg-gray-950/80 transition-colors',
                    TONE_STYLES[entry.tone],
                  )}
                >
                  <div className="flex items-start gap-2 text-[12px] leading-tight">
                    <Icon size={12} className="mt-0.5 shrink-0 opacity-80" aria-hidden="true" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="font-medium">{entry.text}</span>
                        <span className="text-[10px] text-gray-500 shrink-0">
                          {formatTime(entry.timestamp)}
                        </span>
                      </div>
                      {entry.detail && (
                        <p className="text-[11px] text-gray-400 break-words mt-0.5 line-clamp-3">
                          {entry.detail}
                        </p>
                      )}
                      <div className="flex items-center gap-2 mt-0.5 text-[10px] text-gray-500">
                        {entry.agent_id && <span>agent {shortId(entry.agent_id)}</span>}
                        {entry.task_id && <span>task {shortId(entry.task_id)}</span>}
                      </div>
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </section>
  )
}
