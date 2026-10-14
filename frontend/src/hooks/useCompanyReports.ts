import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { companyApi, companySessionVersion } from '@/api/company'
import type { NativeReportProfileRef, PlanView, ResolveReportProfile } from '@/types/company'
import { evidenceSelection, reportPeriod, reportSelection } from './companyReportInputs'

export function useSavedCompanyReport(company: string, report: string | undefined) {
  return useQuery({ queryKey: ['company', company, 'report', report, companySessionVersion()],
    queryFn: () => companyApi.report(company, report!), enabled: Boolean(report), retry: false, staleTime: 0 })
}

export function useNewCompanyReport(plan: PlanView) {
  const [error, setError] = useState<string | null>(null)
  const mutation = useMutation({ retry: false, mutationFn: (body: Parameters<typeof companyApi.saveReport>[1]) =>
    companyApi.saveReport(plan.company_id, body) })
  const save = (author: string, tasks: string[], start: string, end: string) => {
    if (mutation.isPending || mutation.isSuccess || mutation.isError) return
    try {
      const edges = plan.declaration.verification.filter(edge => edge.author_task_id === author)
      if (plan.state !== 'approved' || !plan.is_current_head || edges.length !== 1)
        throw new Error('Choose an author with one independent verifier in the current approved plan.')
      const selected = reportSelection(tasks, plan.work.map(row => row.work.task_id), author, edges[0].verifier_task_id)
      setError(null)
      mutation.mutate({ plan_revision_id: plan.reference.plan_revision_id, author_task_id: author,
        selected_task_ids: selected, ...reportPeriod(start, end) })
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Report selection unavailable.') }
  }
  return { error, mutation, save, newSnapshot: () => { setError(null); mutation.reset() } }
}

export function useReportPreparation(company: string, report: string) {
  const client = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const resolve = useMutation({ retry: false, mutationFn: (body: ResolveReportProfile) => companyApi.resolveReportProfile(company, body) })
  const prepare = useMutation({ retry: false, mutationFn: (reference: NativeReportProfileRef) => companyApi.prepareReportAuthor(company, reference),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['company', company] }) } })
  const select = (commitment: string, evidence: string) => {
    try {
      if (!commitment) throw new Error('Choose an existing commitment for this report plan.')
      const evidence_ids = evidenceSelection(evidence)
      setError(null); prepare.reset()
      resolve.mutate({ report_id: report, commitment_id: commitment, evidence_ids })
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Report profile unavailable.') }
  }
  const reset = () => { setError(null); resolve.reset(); prepare.reset() }
  return { error, resolve, prepare, select, reset }
}
