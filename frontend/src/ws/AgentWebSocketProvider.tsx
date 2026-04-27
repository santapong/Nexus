import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { toast } from 'sonner'
import { useAgentEventStore, type RawAgentEvent } from './agentEventStore'

const API_URL = import.meta.env.VITE_API_URL || ''
const RECONNECT_DELAY_MS = 3_000

function safeParse(data: string): RawAgentEvent | null {
  try {
    const parsed = JSON.parse(data) as RawAgentEvent
    if (typeof parsed === 'object' && parsed !== null) return parsed
  } catch {
    // ignore — non-JSON heartbeat or noise
  }
  return null
}

function shortId(id?: string): string {
  if (!id) return ''
  return id.length > 8 ? `${id.slice(0, 6)}…` : id
}

export function AgentWebSocketProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient()
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout>>()
  const setConnectionState = useAgentEventStore((s) => s.setConnectionState)
  const pushEvent = useAgentEventStore((s) => s.pushEvent)

  useEffect(() => {
    function handleMessage(raw: RawAgentEvent) {
      pushEvent(raw)

      switch (raw.event) {
        case 'task_started':
          toast.message('Task started', {
            description: raw.instruction_snippet ?? `task ${shortId(raw.task_id)}`,
          })
          void queryClient.invalidateQueries({ queryKey: ['tasks'] })
          break
        case 'task_completed':
          toast.success('Task completed', {
            description: `task ${shortId(raw.task_id)}`,
          })
          void queryClient.invalidateQueries({ queryKey: ['tasks'] })
          break
        case 'task_failed':
          toast.error('Task failed', {
            description: raw.error ?? `task ${shortId(raw.task_id)}`,
          })
          void queryClient.invalidateQueries({ queryKey: ['tasks'] })
          break
        case 'approval_requested':
          toast.warning('Approval needed', {
            description: raw.error ?? `agent ${shortId(raw.agent_id)} is waiting`,
          })
          void queryClient.invalidateQueries({ queryKey: ['approvals'] })
          break
        case 'approval_resolved':
          void queryClient.invalidateQueries({ queryKey: ['approvals'] })
          break
        case 'agent_state_change':
        case 'agent_thinking_update':
        case 'meeting_message_published':
        case 'meeting_convergence_update':
        case 'task_trace_step':
        case 'agent_heartbeat':
          // Live UX only — no toast spam, no full refetch.
          break
        default:
          // Unknown event: be conservative and invalidate task list (back-compat).
          void queryClient.invalidateQueries({ queryKey: ['tasks'] })
          void queryClient.invalidateQueries({ queryKey: ['approvals'] })
      }
    }

    function connect() {
      const wsUrl = (API_URL || window.location.origin)
        .replace(/^http/, 'ws')
        .replace(/\/$/, '')
      setConnectionState('connecting')
      const ws = new WebSocket(`${wsUrl}/ws/agents`)
      wsRef.current = ws

      ws.onopen = () => {
        setConnectionState('open')
      }

      ws.onmessage = (event: MessageEvent<string>) => {
        const parsed = safeParse(event.data)
        if (parsed) handleMessage(parsed)
      }

      ws.onclose = () => {
        setConnectionState('closed')
        reconnectTimerRef.current = setTimeout(connect, RECONNECT_DELAY_MS)
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    connect()

    return () => {
      clearTimeout(reconnectTimerRef.current)
      wsRef.current?.close()
    }
  }, [queryClient, pushEvent, setConnectionState])

  return <>{children}</>
}
