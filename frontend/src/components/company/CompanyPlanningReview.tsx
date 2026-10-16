import { useState } from 'react'
import { companySessionVersion } from '@/api/company'
import { CompanyPlanningInput } from '@/components/company/CompanyPlanningInput'
import { CompanyQueryState } from '@/components/company/CompanyStatus'
import { Button } from '@/components/ui/button'
import { useCompanyView } from '@/hooks/useCompany'
import { usePlanningDecision, usePlanningInput } from '@/hooks/useCompanyPlanning'
import { canDecidePlanning, requirePlanningInputReview } from '@/hooks/companyPlanningState'
import type { ActionReview } from '@/types/company'
import type { PlanningInputReview } from '@/types/companyPlanning'

function PlanningDecision({ review, input, paused, refreshing }: {
  review: ActionReview; input: PlanningInputReview; paused: boolean; refreshing: boolean
}) {
  const [reviewed, setReviewed] = useState(false)
  const decision = usePlanningDecision(review.company_id, review.audit.action_id,
    review.audit.proposal_sha256, input.descriptor_sha256)
  const pending = refreshing || decision.isPending
  return <div className="space-y-4"><CompanyPlanningInput data={input} />
    {refreshing ? <p role="status" className="text-sm text-gray-400">Refreshing current access and request. Decisions are paused.</p> : null}
    {paused ? <p role="status" className="text-sm text-amber-500">Company intake is paused.</p> : null}
    {canDecidePlanning(review, paused) ? <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
      <label className="flex items-start gap-3 text-sm text-gray-300"><input type="checkbox"
        checked={reviewed} disabled={pending} onChange={event => setReviewed(event.target.checked)} className="mt-1 accent-indigo-500" />
        I reviewed the model, exact input and maximum reservation.</label>
      <div className="flex flex-wrap gap-3"><Button disabled={!reviewed || pending} onClick={() => decision.mutate(true)}>Approve planning request</Button>
        <Button variant="outline" disabled={!reviewed || pending} onClick={() => decision.mutate(false)}>Reject request</Button></div>
    </section> : null}
    {decision.isError ? <p role="alert" className="text-sm text-red-400">{decision.error.message}</p> : null}
    {decision.isSuccess ? <p role="status" className="text-sm text-emerald-500">Exact owner decision saved.</p> : null}
  </div>
}

export function CompanyPlanningReview({ review, refreshing }: { review: ActionReview; refreshing: boolean }) {
  const input = usePlanningInput(review.company_id, review.audit.action_id)
  const company = useCompanyView(review.company_id)
  const refresh = () => { void input.refetch(); void company.refetch() }
  if (input.isPending || input.isError || !input.data) return <CompanyQueryState pending={input.isPending}
    error={input.error} refresh={refresh} />
  if (company.isPending || company.isError || !company.data) return <CompanyQueryState pending={company.isPending}
    error={company.error} refresh={refresh} />
  try {
    requirePlanningInputReview(input.data, review, review.company_id, review.audit.action_id,
      review.audit.proposal_sha256, input.data.descriptor_sha256)
  } catch (error) {
    return <CompanyQueryState pending={false} error={error instanceof Error ? error : new Error('Planning input unavailable')} refresh={refresh} />
  }
  return <PlanningDecision key={`${companySessionVersion()}:${review.audit.proposal_sha256}:${input.data.descriptor_sha256}`}
    review={review} input={input.data} paused={company.data.paused}
    refreshing={refreshing || input.isFetching || company.isFetching} />
}
