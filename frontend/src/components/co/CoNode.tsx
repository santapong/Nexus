import { memo } from 'react'
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react'
import { STATE_META } from '@/components/agents/stateMeta'
import { useAgentEventStore } from '@/ws/agentEventStore'
import { cn } from '@/lib/utils'

export interface CoNodeData extends Record<string, unknown> {
  agentId: string
  expanded: boolean
}

export type CoFlowNode = Node<CoNodeData, 'co'>

/**
 * The central "Co" node — your personal chief of staff. Clicking it
 * expands/collapses the team DAG (handled by CoCanvas via onNodeClick).
 */
export const CoNode = memo(function CoNode({ data }: NodeProps<CoFlowNode>) {
  const live = useAgentEventStore((s) => s.agents[data.agentId])
  const state = live?.state ?? 'idle'
  const meta = STATE_META[state]

  return (
    <div
      className={cn(
        'flex h-40 w-40 flex-col items-center justify-center rounded-full border-2',
        'border-indigo-400/70 bg-gradient-to-br from-indigo-950 via-gray-900 to-gray-950',
        'shadow-[0_0_45px_-5px_rgba(99,102,241,0.55)] ring-4',
        meta.ring,
        state !== 'idle' && 'animate-pulse',
      )}
    >
      <span className="text-4xl">🤝</span>
      <div className="mt-1 text-lg font-bold tracking-wide text-indigo-100">Co</div>
      <div className="flex items-center gap-1.5 text-[11px] text-indigo-300/90">
        <span className={cn('h-2 w-2 rounded-full', meta.dot)} />
        {meta.label}
      </div>
      <div className="mt-0.5 text-[10px] text-gray-500">
        {data.expanded ? 'click to collapse team' : 'click to reveal team'}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-indigo-500" />
    </div>
  )
})
