import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '../api/client'

export function useEvalScores(period = '7d') {
  return useQuery({
    queryKey: ['eval', 'scores', period],
    queryFn: () => api.getEvalScores(period),
    refetchInterval: 60_000,
  })
}

export function useTriggerEvalRun() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.triggerEvalRun(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['eval'] })
      toast.success('Eval run triggered')
    },
    onError: () => {
      toast.error('Failed to trigger eval run')
    },
  })
}
