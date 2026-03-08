import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

const API_URL = import.meta.env.VITE_API_URL || ''
const RECONNECT_DELAY_MS = 3_000

export function AgentWebSocketProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient()
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    function connect() {
      const wsUrl = (API_URL || window.location.origin)
        .replace(/^http/, 'ws')
        .replace(/\/$/, '')
      const ws = new WebSocket(`${wsUrl}/ws/agents`)
      wsRef.current = ws

      ws.onmessage = () => {
        void queryClient.invalidateQueries({ queryKey: ['tasks'] })
        void queryClient.invalidateQueries({ queryKey: ['approvals'] })
      }

      ws.onclose = () => {
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
  }, [queryClient])

  return <>{children}</>
}
