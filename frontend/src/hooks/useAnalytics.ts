import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export function usePerformance(period = '30d') {
  return useQuery({
    queryKey: ['analytics', 'performance', period],
    queryFn: () => api.getPerformance(period),
    refetchInterval: 30_000,
  })
}

export function useCosts(period = '30d') {
  return useQuery({
    queryKey: ['analytics', 'costs', period],
    queryFn: () => api.getCosts(period),
    refetchInterval: 30_000,
  })
}

export function useDeadLetters() {
  return useQuery({
    queryKey: ['analytics', 'dead-letters'],
    queryFn: () => api.getDeadLetters(),
    refetchInterval: 60_000,
  })
}

export function useTaskReplay(taskId: string) {
  return useQuery({
    queryKey: ['task-replay', taskId],
    queryFn: () => api.getTaskReplay(taskId),
    enabled: !!taskId,
  })
}
