import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
    },
  })
}

export function useRevokeA2AToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.revokeA2AToken(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['a2a-tokens'] })
    },
  })
}

export function useRotateA2AToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.rotateA2AToken(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['a2a-tokens'] })
    },
  })
}
