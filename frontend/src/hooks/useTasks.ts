import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '../api/client'

export function useTasks() {
  return useQuery({
    queryKey: ['tasks'],
    queryFn: () => api.listTasks(),
    refetchInterval: 3_000,
  })
}

export interface CreateTaskInput {
  instruction: string
  attachments?: string[]
}

export function useCreateTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: string | CreateTaskInput) => {
      const { instruction, attachments } =
        typeof input === 'string' ? { instruction: input, attachments: undefined } : input
      return api.createTask(instruction, attachments)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
      toast.success('Task submitted successfully')
    },
    onError: () => {
      toast.error('Failed to submit task')
    },
  })
}
