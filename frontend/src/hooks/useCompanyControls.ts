import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { companyApi, companySessionVersion } from '@/api/company'
import type { WorkCancellationIntent } from '@/types/company'

export function useCompanyControls(id: string) {
  return useQuery({ queryKey: ['company', id, 'controls', companySessionVersion()],
    queryFn: () => companyApi.controls(id), retry: false, staleTime: 0 })
}

export function useCompanyPause(id: string) {
  const client = useQueryClient()
  return useMutation({ mutationFn: (paused: boolean) => companyApi.pause(id, paused),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['company', id] }) } })
}

export function useWorkCancellation(id: string) {
  const client = useQueryClient()
  return useMutation({ mutationFn: (body: WorkCancellationIntent) => companyApi.cancelWork(id, body),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['company', id] }) } })
}
