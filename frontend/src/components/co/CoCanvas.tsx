import { useMemo } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useAgents } from '@/hooks/useAgents'
import { useAgentEventStore } from '@/ws/agentEventStore'
import type { AgentInfo } from '@/types'
import { AgentNode, type AgentNodeData } from './AgentNode'
import { CoNode, type CoNodeData } from './CoNode'

const nodeTypes: NodeTypes = {
  co: CoNode,
  agent: AgentNode,
}

interface CoCanvasProps {
  expanded: boolean
  selectedAgentId: string | null
  onToggleExpanded: () => void
  onSelectAgent: (agentId: string | null) => void
}

const CENTER = { x: 0, y: 0 }
const RADIUS_Y = 330

function specialistPositions(count: number): Array<{ x: number; y: number }> {
  // Fan the team out in an arc below Co — readable at 5-7 nodes, no
  // layout engine needed (nodes are few; ADR-092 defers dagre/elk).
  if (count === 0) return []
  const spread = Math.PI * 0.8 // 144° arc
  const start = Math.PI / 2 - spread / 2
  return Array.from({ length: count }, (_, i) => {
    const angle = count === 1 ? Math.PI / 2 : start + (spread * i) / (count - 1)
    return {
      x: CENTER.x + Math.cos(angle) * 420 - 88, // offset by half node width
      y: CENTER.y + Math.sin(angle) * RADIUS_Y + 60,
    }
  })
}

/**
 * The Co canvas — one central node that expands into the live agent DAG.
 * Node status animates from the WebSocket event store; edges animate while
 * the target agent is thinking or calling a tool.
 */
export function CoCanvas({
  expanded,
  selectedAgentId,
  onToggleExpanded,
  onSelectAgent,
}: CoCanvasProps) {
  const { data: agents } = useAgents()
  const liveAgents = useAgentEventStore((s) => s.agents)

  const { nodes, edges } = useMemo(() => {
    const list: AgentInfo[] = agents ?? []
    const co = list.find((a) => a.role === 'ceo')
    const team = list.filter((a) => a.role !== 'ceo' && a.is_active)

    const coNode: Node<CoNodeData> = {
      id: 'co',
      type: 'co',
      position: { x: CENTER.x - 80, y: CENTER.y - 80 },
      // Live events key agents by their DB UUID (runner passes
      // str(agent_db.id) as agent_id).
      data: { agentId: co?.id ?? 'ceo', expanded },
      draggable: false,
    }

    if (!expanded) {
      return { nodes: [coNode] as Node[], edges: [] as Edge[] }
    }

    const positions = specialistPositions(team.length)
    const teamNodes: Node<AgentNodeData>[] = team.map((agent, i) => ({
      id: agent.id,
      type: 'agent',
      position: positions[i] ?? { x: 0, y: RADIUS_Y },
      data: {
        agentId: agent.id,
        role: agent.role,
        name: agent.name,
        llmModel: agent.llm_model,
        isActive: agent.is_active,
        selected: selectedAgentId === agent.id,
      },
    }))

    const teamEdges: Edge[] = team.map((agent) => {
      const live = liveAgents[agent.id]
      const busy = live?.state === 'thinking' || live?.state === 'calling_tool'
      return {
        id: `co-${agent.id}`,
        source: 'co',
        target: agent.id,
        animated: busy,
        style: {
          stroke: busy ? '#818cf8' : '#374151',
          strokeWidth: busy ? 2.5 : 1.5,
        },
      }
    })

    return { nodes: [coNode, ...teamNodes] as Node[], edges: teamEdges }
  }, [agents, expanded, liveAgents, selectedAgentId])

  const handleNodeClick: NodeMouseHandler = (_event, node) => {
    if (node.id === 'co') {
      onToggleExpanded()
      return
    }
    const data = node.data as AgentNodeData
    onSelectAgent(selectedAgentId === data.agentId ? null : data.agentId)
  }

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={handleNodeClick}
      colorMode="dark"
      fitView
      fitViewOptions={{ padding: 0.35, duration: 300 }}
      proOptions={{ hideAttribution: false }}
      nodesConnectable={false}
      className="bg-gray-950"
    >
      <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#1f2937" />
      <Controls showInteractive={false} position="bottom-right" />
    </ReactFlow>
  )
}
