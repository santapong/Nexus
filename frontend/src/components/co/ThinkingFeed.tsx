import { useMemo } from 'react'
import { X } from 'lucide-react'
import { useAgentEventStore, type ThinkingEntry } from '@/ws/agentEventStore'
import { cn } from '@/lib/utils'

const TONE_DOT: Record<ThinkingEntry['tone'], string> = {
  info: 'bg-gray-500',
  success: 'bg-emerald-400',
  warn: 'bg-amber-400',
  error: 'bg-red-500',
  thinking: 'bg-blue-400',
  tool: 'bg-amber-400',
}

interface ThinkingFeedProps {
  selectedAgentId: string | null
  onClearSelection: () => void
}

/** Compact live activity feed beside the Co canvas, filterable by agent. */
export function ThinkingFeed({ selectedAgentId, onClearSelection }: ThinkingFeedProps) {
  const thinking = useAgentEventStore((s) => s.thinking)

  const entries = useMemo(
    () =>
      selectedAgentId
        ? thinking.filter((e) => e.agent_id === selectedAgentId)
        : thinking,
    [thinking, selectedAgentId],
  )

  return (
    <aside className="flex h-full w-72 flex-col border-l border-gray-800 bg-gray-950/90">
      <header className="flex items-center justify-between border-b border-gray-800 px-3 py-2.5">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
          Team activity
        </h2>
        {selectedAgentId && (
          <button
            type="button"
            onClick={onClearSelection}
            className="flex items-center gap-1 rounded-md bg-gray-800 px-2 py-0.5 text-[11px] text-gray-300 hover:bg-gray-700"
          >
            filtered <X size={11} />
          </button>
        )}
      </header>
      <div className="flex-1 space-y-1 overflow-y-auto p-2">
        {entries.length === 0 && (
          <p className="px-2 py-6 text-center text-xs text-gray-600">
            Quiet for now — give Co something to do.
          </p>
        )}
        {entries.map((entry) => (
          <div key={entry.id} className="rounded-lg px-2 py-1.5 hover:bg-gray-900">
            <div className="flex items-center gap-1.5">
              <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', TONE_DOT[entry.tone])} />
              <span className="truncate text-xs text-gray-200">{entry.text}</span>
            </div>
            {entry.detail && (
              <p className="ml-3 line-clamp-2 text-[11px] leading-tight text-gray-500">
                {entry.detail}
              </p>
            )}
          </div>
        ))}
      </div>
    </aside>
  )
}
