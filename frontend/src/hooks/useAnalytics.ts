import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { SubmitTaskFeedbackRequest } from '../types'

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

// --- Phase 9 Track 1: feedback + approval rates -----------------------------

export function useApprovalRates(period = '30d') {
  return useQuery({
    queryKey: ['analytics', 'approval-rates', period],
    queryFn: () => api.getApprovalRates(period),
    refetchInterval: 60_000,
  })
}

export function useTaskFeedback(taskId: string) {
  return useQuery({
    queryKey: ['task-feedback', taskId],
    queryFn: () => api.listTaskFeedback(taskId),
    enabled: !!taskId,
  })
}

export function useSubmitTaskFeedback(taskId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: SubmitTaskFeedbackRequest) =>
      api.submitTaskFeedback(taskId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['task-feedback', taskId] })
      queryClient.invalidateQueries({ queryKey: ['analytics', 'approval-rates'] })
    },
  })
}
