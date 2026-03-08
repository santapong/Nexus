import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

export function useTasks() {
  return useQuery({
    queryKey: ['tasks'],
    queryFn: () => api.listTasks(),
    refetchInterval: 3_000,
  })
}

export function useCreateTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (instruction: string) => api.createTask(instruction),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
}
