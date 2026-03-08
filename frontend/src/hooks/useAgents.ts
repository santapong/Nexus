import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export function useAgents() {
  return useQuery({
    queryKey: ['agents'],
    queryFn: api.listAgents,
    refetchInterval: 30_000,
  })
}
