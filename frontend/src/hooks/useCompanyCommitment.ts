import { useState } from 'react'
import { usePublishCommitment } from './useCompany'
import type { CommitmentPublish, PlanView } from '@/types/company'

export function useCompanyCommitment(plan: PlanView) {
  const mutation = usePublishCommitment(plan.company_id)
  const [error, setError] = useState<string | null>(null)
  const publish = (deliverable: string, responsible: string, due: string) => {
    setError(null)
    if (!deliverable.trim() || !responsible) { setError('Choose a responsible member and describe the deliverable.'); return }
    const chosen = due ? new Date(due) : null
    if (chosen && !Number.isFinite(chosen.getTime())) { setError('Choose a valid due instant or leave it unscheduled.'); return }
    const body: CommitmentPublish = {
      version: 'v1', expected_revision_id: null,
      definition: { schema_version: 'nexus.company.management.v1', company_id: plan.company_id,
        commitment_id: crypto.randomUUID(), goal: plan.declaration.goal, plan: plan.reference,
        responsible_id: responsible, deliverable: deliverable.trim(),
        due: { source_time: { precision: 'unknown', value: null, basis: 'Owner commitment declaration' },
          actionable_at: chosen?.toISOString() ?? null, actionable_basis: chosen ? 'operator_explicit' : null },
        work: plan.declaration.children.map(child => child.binding) },
    }
    mutation.mutate(body)
  }
  return { publish, error, mutation }
}
