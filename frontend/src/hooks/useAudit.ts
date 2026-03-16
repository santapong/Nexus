import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

interface AuditFilters {
  event_type?: string
  agent_id?: string
  limit?: number
  offset?: number
}

export function useAuditEvents(filters?: AuditFilters) {
  return useQuery({
    queryKey: ['audit', 'events', filters],
    queryFn: () => api.getAuditEvents(filters),
    refetchInterval: 30_000,
  })
}

export function useTaskTimeline(taskId: string) {
  return useQuery({
    queryKey: ['audit', 'timeline', taskId],
    queryFn: () => api.getTaskTimeline(taskId),
    enabled: !!taskId,
  })
}
