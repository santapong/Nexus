import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { companySessionVersion } from '@/api/company'
import { companyPlanningApi } from '@/api/companyPlanning'
import { decidePlanning } from '@/hooks/companyPlanningActions'
import type { PlanningGoalSelection, RecoverPlanningWaitRequest } from '@/types/companyPlanning'

export function usePlanningInput(company: string, action: string) {
  return useQuery({ queryKey: ['company', company, 'planning-input', action, companySessionVersion()],
    queryFn: () => companyPlanningApi.input(company, action), retry: false, staleTime: 0, gcTime: 0 })
}

export function usePlanningDecision(company: string, action: string, hash: string, descriptor: string) {
  const client = useQueryClient()
  return useMutation({ mutationFn: (approved: boolean) => decidePlanning(company, action, hash, descriptor, approved),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['company', company] }) } })
}

export function usePlanningStatus(company: string, goal: string) {
  return useQuery({ queryKey: ['company', company, 'planning-status', goal, companySessionVersion()],
    queryFn: () => companyPlanningApi.status(company, goal), retry: false, staleTime: 0, gcTime: 0 })
}

export function usePlanningCandidate(company: string, action: string, head: string | null) {
  return useQuery({ queryKey: ['company', company, 'planning-candidate', action, head, companySessionVersion()],
    queryFn: () => {
      if (head === null) throw new Error('The current plan is unavailable. Refresh its record.')
      return companyPlanningApi.candidate(company, action, head)
    }, enabled: head !== null, retry: false, staleTime: 0, gcTime: 0 })
}

function usePlanningMutation<T, R>(company: string, mutationFn: (value: T) => Promise<R>) {
  const client = useQueryClient()
  return useMutation({ mutationFn,
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['company', company] }) } })
}

export function usePlanningBootstrap(company: string) {
  return usePlanningMutation(company, (body: PlanningGoalSelection) => companyPlanningApi.bootstrap(company, body))
}

export function usePlanningPrepare(company: string) {
  return usePlanningMutation(company, (body: PlanningGoalSelection) => companyPlanningApi.prepare(company, body))
}

export function usePlanningDispatch(company: string, action: string) {
  return usePlanningMutation(company, (hash: string) => companyPlanningApi.dispatch(company, action, hash))
}

export function usePlanningProposal(company: string, action: string) {
  return usePlanningMutation(company, (body: PlanningGoalSelection) => companyPlanningApi.propose(company, action, body))
}

export function usePlanningRecoverWait(company: string, action: string) {
  return usePlanningMutation(company, (body: RecoverPlanningWaitRequest) => companyPlanningApi.recoverWait(company, action, body))
}
