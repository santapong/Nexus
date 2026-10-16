import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { companyApi, companySessionVersion } from '@/api/company'
import { searchRequest } from '@/hooks/companyGoalDraft'
import type { GoalPublish } from '@/types/company'

export function useCompanyKnowledge(company: string, query: string) {
  return useQuery({ queryKey: ['company', company, 'knowledge', query, companySessionVersion()],
    queryFn: () => companyApi.searchKnowledge(company, searchRequest(query)), enabled: Boolean(query),
    retry: false, staleTime: 0 })
}

export function useCompanyEvidence(company: string, evidence: string | null) {
  return useQuery({ queryKey: ['company', company, 'evidence', evidence, companySessionVersion()],
    queryFn: () => companyApi.evidence(company, evidence!), enabled: Boolean(evidence), retry: false, staleTime: 0 })
}

export function useCreateCompanyGoal(company: string) {
  const client = useQueryClient()
  return useMutation({ mutationFn: (body: GoalPublish) => companyApi.createGoal(company, body), retry: false,
    onSuccess: async () => { await Promise.all([
      client.invalidateQueries({ queryKey: ['company', company, 'overview'] }),
      client.invalidateQueries({ queryKey: ['company', company, 'today'] }),
    ]) } })
}
