import { memo } from 'react'
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react'
import { ROLE_CONFIG, STATE_META } from '@/components/agents/stateMeta'
import { useAgentEventStore } from '@/ws/agentEventStore'
import { cn } from '@/lib/utils'

export interface AgentNodeData extends Record<string, unknown> {
  agentId: string
  role: string
  name: string
  llmModel: string
  isActive: boolean
  selected?: boolean
}

export type AgentFlowNode = Node<AgentNodeData, 'agent'>

/**
 * A specialist node on the Co canvas. Live state (ring, pulse, dot) binds
 * directly to the WebSocket event store — no polling.
 */
export const AgentNode = memo(function AgentNode({ data }: NodeProps<AgentFlowNode>) {
  const live = useAgentEventStore((s) => s.agents[data.agentId])
  const state = live?.state ?? 'idle'
  const meta = STATE_META[state]
  const role = ROLE_CONFIG[data.role] ?? {
    emoji: '🤖',
    color: 'border-gray-500',
    label: data.role,
  }
  const StateIcon = meta.icon

  return (
    <div
      className={cn(
        'w-44 rounded-xl border-2 bg-gray-900/95 px-3 py-2.5 shadow-lg ring-2',
        role.color,
        meta.ring,
        meta.pulse,
        data.selected && 'outline outline-2 outline-offset-2 outline-indigo-400',
        !data.isActive && 'opacity-50',
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-600" />
      <div className="flex items-center gap-2">
        <span className="text-2xl leading-none">{role.emoji}</span>
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-gray-100">{data.name}</div>
          <div className="truncate text-[11px] text-gray-400">{role.label}</div>
        </div>
      </div>
      <div className="mt-2 flex items-center gap-1.5 text-[11px] text-gray-300">
        <span className={cn('h-2 w-2 rounded-full', meta.dot)} />
        <StateIcon size={12} className="text-gray-400" />
        <span>{meta.label}</span>
      </div>
      {live?.instruction_snippet && state !== 'idle' && (
        <div className="mt-1.5 line-clamp-2 text-[10px] leading-tight text-gray-500">
          {live.instruction_snippet}
        </div>
      )}
    </div>
  )
})
