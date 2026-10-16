import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { companySessionVersion } from '@/api/company'
import { companyPlanningApi } from '@/api/companyPlanning'
import { decidePlanning } from '@/hooks/companyPlanningActions'

export function usePlanningInput(company: string, action: string) {
  return useQuery({ queryKey: ['company', company, 'planning-input', action, companySessionVersion()],
    queryFn: () => companyPlanningApi.input(company, action), retry: false, staleTime: 0, gcTime: 0 })
}

export function usePlanningDecision(company: string, action: string, hash: string, descriptor: string) {
  const client = useQueryClient()
  return useMutation({ mutationFn: (approved: boolean) => decidePlanning(company, action, hash, descriptor, approved),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['company', company] }) } })
}
