import { useState } from 'react'
import { Link, useOutletContext, useParams } from 'react-router-dom'
import { useActionReview, useExactActionDecision } from '@/hooks/useCompany'
import type { ActionReview, CompanyIdentity } from '@/types/company'
import { CompanyQueryState, money, StateLabel } from '@/components/company/CompanyStatus'
import { Button } from '@/components/ui/button'
import { CompanyPlanningReview } from '@/components/company/CompanyPlanningReview'
import { isPlanningAction } from '@/hooks/companyPlanningState'

function ExactReview({ data }: { data: ActionReview }) {
  const [reviewed, setReviewed] = useState(false)
  const action = useExactActionDecision(data.company_id, data.audit.action_id, data.audit.proposal_sha256)
  const detail = data.detail
  if (!detail || data.availability !== 'available') return <div role="status"
    className="rounded-lg bg-gray-900 border border-gray-800 p-5 space-y-3">
    <h3 className="font-semibold text-white">Exact review unavailable</h3>
    <p className="text-sm text-gray-400">Current source access or resource state does not permit viewing this action. Approval controls are unavailable.</p>
    <p className="text-xs font-mono break-all text-gray-500">Recorded proposal {data.audit.proposal_sha256}</p>
  </div>
  const pending = ['proposed', 'awaiting_approval', 'validated'].includes(data.audit.state)
  return <section className="rounded-lg bg-gray-900 border border-gray-800 p-5 space-y-4">
    <h3 className="font-semibold text-white">Concrete action</h3>
    <div className="grid sm:grid-cols-2 gap-3 text-sm"><p className="text-gray-400">Tool <span className="text-gray-200">{detail.proposal.tool}</span></p>
      <p className="text-gray-400">Version <span className="text-gray-200">{detail.proposal.tool_version}</span></p>
      <p className="text-gray-400">Resource <span className="text-gray-200">{detail.proposal.resource}</span></p>
      <p className="text-gray-400">Estimated cost <span className="text-gray-200">{money(detail.proposal.estimated_cost_usd)}</span></p></div>
    <p className="text-xs text-gray-500">Policy {detail.proposal.policy_version} · Pricebook {detail.proposal.price_version}</p>
    <pre className="overflow-auto rounded-lg bg-gray-950 border border-gray-800 p-4 text-sm text-gray-300 whitespace-pre-wrap break-all"
      aria-label="Exact action parameters">{JSON.stringify(detail.proposal.parameters, null, 2)}</pre>
    {detail.proposal.preconditions.length > 0 && <ul className="text-xs text-gray-400">{detail.proposal.preconditions.map(condition =>
      <li key={condition.resource}>{condition.resource} · {condition.revision}</li>)}</ul>}
    <p className="font-mono text-xs break-all text-gray-500">Exact hash {detail.proposal_sha256}</p>
    <details className="text-xs text-gray-400"><summary className="cursor-pointer">Exact work identity</summary>
      <div className="mt-3 font-mono break-all space-y-2"><p>Task {detail.task_id}</p><p>Trace {detail.trace_id}</p><p>Run {detail.run_id}</p></div>
      <Link className="block text-indigo-400 mt-3" to={`/company/work/${detail.task_id}`}>Inspect native work and costs</Link></details>
    {pending && <>
      <label className="flex items-start gap-3 text-sm text-gray-300"><input type="checkbox" className="mt-1 accent-indigo-500"
        checked={reviewed} onChange={event => setReviewed(event.target.checked)} />I reviewed the concrete parameters, resource and cost.</label>
      <div className="flex gap-3"><Button disabled={!reviewed || action.isPending} onClick={() => action.mutate(true)}>Approve exact action</Button>
        <Button variant="outline" disabled={!reviewed || action.isPending} onClick={() => action.mutate(false)}>Reject exact action</Button></div>
    </>}
    {action.isError && <p role="alert" className="text-sm text-red-400">{action.error.message}</p>}
    {action.isSuccess && <p role="status" className="text-sm text-emerald-500">Exact owner decision saved. This decision did not dispatch an action.</p>}
  </section>
}

export function CompanyActionReviewPage() {
  const identity = useOutletContext<CompanyIdentity>()
  const { actionId } = useParams()
  const query = useActionReview(identity.company_id, actionId)
  if (query.isPending || query.isError || !query.data) return <CompanyQueryState pending={query.isPending}
    error={query.error} refresh={() => { void query.refetch() }} />
  return <div className="space-y-5"><div className="flex flex-wrap justify-between gap-3">
    <h2 className="text-2xl font-semibold text-white">Action review</h2><StateLabel>{query.data.audit.state.replace(/_/g, ' ')}</StateLabel></div>
    {isPlanningAction(query.data)
      ? <CompanyPlanningReview review={query.data} refreshing={query.isFetching} />
      : <ExactReview key={query.data.audit.proposal_sha256} data={query.data} />}
  </div>
}
