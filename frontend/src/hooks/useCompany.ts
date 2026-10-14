import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { companyApi, companySessionVersion } from '@/api/company'
import type { CommitmentPublish, PlanDecision } from '@/types/company'

export function useCompanyIdentity() {
  return useQuery({ queryKey: ['company-identity', companySessionVersion()], queryFn: companyApi.identity, retry: false, staleTime: 0 })
}

export function useCompanyView(id: string | undefined, after?: string | null) {
  return useQuery({ queryKey: ['company', id, 'overview', after, companySessionVersion()], queryFn: () => companyApi.company(id!, after),
    enabled: Boolean(id), retry: false, staleTime: 0 })
}

export function useCompanyToday(id: string | undefined, after?: string | null) {
  return useQuery({ queryKey: ['company', id, 'today', after, companySessionVersion()], queryFn: () => companyApi.today(id!, after),
    enabled: Boolean(id), retry: false, staleTime: 0 })
}

export function useCompanyApprovals(id: string | undefined, after?: string | null) {
  return useQuery({ queryKey: ['company', id, 'approvals', after, companySessionVersion()], queryFn: () => companyApi.approvals(id!, after),
    enabled: Boolean(id), retry: false, staleTime: 0 })
}

export function useCompanyPlan(id: string | undefined, plan: string | undefined, revision?: string | null) {
  return useQuery({ queryKey: ['company', id, 'plan', plan, revision, companySessionVersion()], queryFn: () => companyApi.plan(id!, plan!, revision),
    enabled: Boolean(id && plan), retry: false, staleTime: 0 })
}

export function useCompanyWork(id: string | undefined, task: string | undefined) {
  return useQuery({ queryKey: ['company', id, 'work', task, companySessionVersion()], queryFn: () => companyApi.work(id!, task!),
    enabled: Boolean(id && task), retry: false, staleTime: 0 })
}

export function useCompanyDecision(id: string) {
  const client = useQueryClient()
  return useMutation({ mutationFn: ({ revision, kind, body }: {
    revision: string; kind: 'approve' | 'revoke'; body: PlanDecision
  }) => companyApi.decision(id, revision, kind, body),
  onSuccess: async () => { await client.invalidateQueries({ queryKey: ['company', id] }) } })
}

export function usePublishCommitment(id: string) {
  const client = useQueryClient()
  return useMutation({ mutationFn: (body: CommitmentPublish) => companyApi.publishCommitment(id, body),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['company', id] }) } })
}

export function useActionReview(id: string | undefined, action: string | undefined) {
  return useQuery({ queryKey: ['company', id, 'action-review', action, companySessionVersion()],
    queryFn: () => companyApi.review(id!, action!), enabled: Boolean(id && action), retry: false, staleTime: 0 })
}

export function useExactActionDecision(id: string, action: string, expectedHash: string) {
  const client = useQueryClient()
  return useMutation({ mutationFn: async (approved: boolean) => {
    const current = await companyApi.review(id, action)
    if (!current.detail || current.availability !== 'available' || current.detail.proposal_sha256 !== expectedHash) {
      throw new Error('The exact action can no longer be reviewed. Refresh before deciding.')
    }
    return companyApi.actionDecision(id, current.detail.task_id, action, {
      schema_version: 'nexus.company.api.v1', trace_id: current.detail.trace_id,
      expected_hash: current.detail.proposal_sha256, approved,
    })
  }, onSuccess: async () => { await client.invalidateQueries({ queryKey: ['company', id] }) } })
}
