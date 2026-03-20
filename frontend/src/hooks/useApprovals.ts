import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '../api/client'

export function useApprovals() {
  return useQuery({
    queryKey: ['approvals'],
    queryFn: api.listApprovals,
    refetchInterval: 5_000,
  })
}

export function useResolveApproval() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, approved }: { id: string; approved: boolean }) =>
      api.resolveApproval(id, approved),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ['approvals'] })
      toast.success(variables.approved ? 'Approved' : 'Rejected')
    },
    onError: () => {
      toast.error('Failed to resolve approval')
    },
  })
}
