import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '../api/client'

export function useA2ATokens() {
  return useQuery({
    queryKey: ['a2a-tokens'],
    queryFn: () => api.listA2ATokens(),
    refetchInterval: 30_000,
  })
}

export function useCreateA2AToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ name, skills }: { name: string; skills: string[] }) =>
      api.createA2AToken(name, skills),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['a2a-tokens'] })
      toast.success('A2A token created')
    },
    onError: () => {
      toast.error('Failed to create token')
    },
  })
}

export function useRevokeA2AToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.revokeA2AToken(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['a2a-tokens'] })
      toast.success('Token revoked')
    },
    onError: () => {
      toast.error('Failed to revoke token')
    },
  })
}

export function useRotateA2AToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.rotateA2AToken(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['a2a-tokens'] })
      toast.success('Token rotated')
    },
    onError: () => {
      toast.error('Failed to rotate token')
    },
  })
}
