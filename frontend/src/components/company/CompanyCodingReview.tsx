import { useState } from 'react'
import { companySessionVersion } from '@/api/company'
import { CompanyCodingInput } from '@/components/company/CompanyCodingInput'
import { CompanyGoalCoding } from '@/components/company/CompanyGoalCoding'
import { CompanyQueryState } from '@/components/company/CompanyStatus'
import { Button } from '@/components/ui/button'
import { useCompanyView } from '@/hooks/useCompany'
import { canDecideCoding, requireCodingInputReview } from '@/hooks/companyCodingState'
import { useCodingDecision, useCodingInput } from '@/hooks/useCompanyCoding'
import type { ActionReview } from '@/types/company'
import type { CodingInputReview } from '@/types/companyCoding'

function CodingDecision({ review, input, paused, refreshing }: {
  review: ActionReview; input: CodingInputReview; paused: boolean; refreshing: boolean
}) {
  const [checked, setChecked] = useState(false)
  const decision = useCodingDecision(review.company_id, review.audit.action_id, review.audit.proposal_sha256, input.header_sha256)
  const pending = refreshing || decision.isPending
  return <div className="space-y-4"><CompanyCodingInput data={input} />
    {refreshing ? <p role="status" className="text-sm text-gray-400">Refreshing current access and input. Decisions are paused.</p> : null}
    {paused ? <p role="status" className="text-sm text-amber-500">Company intake is paused.</p> : null}
    {canDecideCoding(review, paused) ? <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
      <label className="flex items-start gap-3 text-sm text-gray-300"><input type="checkbox" className="mt-1 accent-indigo-500"
        checked={checked} disabled={pending} onChange={event => setChecked(event.target.checked)} />
        I reviewed the exact model, source input, file scope and maximum reservation.</label>
      <div className="flex flex-wrap gap-3"><Button disabled={!checked || pending} onClick={() => decision.mutate(true)}>Approve coding request</Button>
        <Button variant="outline" disabled={!checked || pending} onClick={() => decision.mutate(false)}>Reject coding request</Button></div>
    </section> : null}
    {decision.isError ? <p role="alert" className="text-sm text-red-400">{decision.error.message}</p> : null}
    {decision.isSuccess ? <p role="status" className="text-sm text-emerald-500">Exact decision saved. Dispatch is a separate step.</p> : null}
    <CompanyGoalCoding goal={input.prepared.binding.goal} paused={paused} initiallyOpen />
  </div>
}

export function CompanyCodingReview({ review, refreshing }: { review: ActionReview; refreshing: boolean }) {
  const query = useCodingInput(review.company_id, review.audit.action_id)
  const company = useCompanyView(review.company_id)
  const refresh = () => { void query.refetch(); void company.refetch() }
  if (query.isPending || query.isError || !query.data || company.isPending || company.isError || !company.data) {
    return <CompanyQueryState pending={query.isPending || company.isPending} error={query.error ?? company.error} refresh={refresh} />
  }
  try { requireCodingInputReview(query.data, review, review.company_id, review.audit.action_id,
    review.audit.proposal_sha256, query.data.header_sha256) } catch (error) {
    return <CompanyQueryState pending={false} error={error instanceof Error ? error : new Error('Coding input unavailable')} refresh={refresh} />
  }
  return <CodingDecision key={`${companySessionVersion()}:${review.audit.proposal_sha256}:${query.data.header_sha256}`}
    review={review} input={query.data} paused={company.data.paused}
    refreshing={refreshing || query.isFetching || company.isFetching} />
}
