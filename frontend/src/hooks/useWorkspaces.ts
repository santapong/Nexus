import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

export function useWorkspaces() {
  return useQuery({
    queryKey: ['workspaces'],
    queryFn: api.listWorkspaces,
    refetchInterval: 30000,
  })
}

export function useCreateWorkspace() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ name, slug }: { name: string; slug: string }) =>
      api.createWorkspace(name, slug),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['workspaces'] }),
  })
}
