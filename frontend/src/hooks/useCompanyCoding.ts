import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { companySessionVersion } from '@/api/company'
import { companyCodingApi } from '@/api/companyCoding'
import { decideCoding, dispatchCoding } from '@/hooks/companyCodingActions'
import type { CodingGoalSelection, RecoverCodingWaitRequest } from '@/types/companyCoding'

export function useCodingStatus(company: string, goal: string) {
  return useQuery({ queryKey: ['company', company, 'coding-status', goal, companySessionVersion()],
    queryFn: () => companyCodingApi.status(company, goal), retry: false, staleTime: 0, gcTime: 0 })
}

export function useCodingInput(company: string, action: string) {
  return useQuery({ queryKey: ['company', company, 'coding-input', action, companySessionVersion()],
    queryFn: () => companyCodingApi.input(company, action), retry: false, staleTime: 0, gcTime: 0 })
}

export function useCodingCandidate(company: string, action: string, head: string) {
  return useQuery({ queryKey: ['company', company, 'coding-candidate', action, head, companySessionVersion()],
    queryFn: () => companyCodingApi.candidate(company, action, head), retry: false, staleTime: 0, gcTime: 0 })
}

function useCodingMutation<T, R>(company: string, mutationFn: (value: T) => Promise<R>) {
  const client = useQueryClient()
  return useMutation({ mutationFn, onSuccess: async () => { await client.invalidateQueries({ queryKey: ['company', company] }) } })
}

export function useCodingPrepare(company: string) {
  return useCodingMutation(company, (selection: CodingGoalSelection) => companyCodingApi.prepare(company, selection))
}

export function useCodingDecision(company: string, action: string, hash: string, header: string) {
  return useCodingMutation(company, (approved: boolean) => decideCoding(company, action, hash, header, approved))
}

export function useCodingDispatch(company: string, action: string) {
  return useCodingMutation(company, (value: { hash: string; selection: CodingGoalSelection }) =>
    dispatchCoding(company, action, value.hash, value.selection))
}

export function useCodingRecovery(company: string, action: string) {
  return useCodingMutation(company, (selection: RecoverCodingWaitRequest) => companyCodingApi.recoverWait(company, action, selection))
}
