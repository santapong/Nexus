import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { CreateAgentRequest } from '../types'

export function useAgentConfigs() {
  return useQuery({
    queryKey: ['agent-configs'],
    queryFn: api.listAgentConfigs,
    refetchInterval: 30000,
  })
}

export function useCreateCustomAgent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: CreateAgentRequest) => api.createCustomAgent(data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agent-configs'] }),
  })
}

export function useActivateAgent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.activateAgent(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agent-configs'] }),
  })
}

export function useDeactivateAgent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deactivateAgent(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agent-configs'] }),
  })
}
