import { Link, useOutletContext, useParams } from 'react-router-dom'
import { useCompanyWork } from '@/hooks/useCompany'
import type { CompanyIdentity } from '@/types/company'
import { CompanyQueryState, instant, money, StateLabel } from '@/components/company/CompanyStatus'
import { WorkCancellationPanel } from '@/components/company/WorkCancellationPanel'

export function CompanyWorkPage() {
  const identity = useOutletContext<CompanyIdentity>()
  const { taskId } = useParams()
  const query = useCompanyWork(identity.company_id, taskId)
  const data = query.data
  if (query.isPending || query.isError || !data) return <CompanyQueryState pending={query.isPending}
    error={query.error} refresh={() => { void query.refetch() }} />
  const acceptance = data.independent_acceptance
  const allowance = data.lifetime
  return <div className="space-y-5">
    <div><h2 className="text-2xl font-semibold text-white">{data.title}</h2>
      <p className="text-xs text-gray-500 font-mono break-all mt-2">Work {data.work.task_id}</p></div>
    <div className="flex flex-wrap gap-2"><StateLabel>{data.execution_state.replace(/_/g, ' ')}</StateLabel>
      <StateLabel warn={!data.lineage_active}>{data.lineage_active ? 'Registered activity active' : 'Registered activity inactive'}</StateLabel>
      {data.cancellation && <StateLabel warn>Explicitly cancelled{data.cancellation.inherited ? ' by ancestor' : ''}</StateLabel>}</div>
    {data.cancellation && <p className="rounded-lg border border-amber-700/50 p-4 text-sm text-amber-500">{data.cancellation.cancellation.reason}</p>}
    <div className="grid md:grid-cols-2 gap-5">
      <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-3">
        <h3 className="font-semibold text-white">Independent acceptance</h3>
        <p className="text-sm text-gray-300">{acceptance.current_confirmed ? 'Current independent pass' : 'Current acceptance not confirmed'}</p>
        {acceptance.historical_verdict && <p className="text-xs text-gray-400">Recorded verdict: {acceptance.historical_verdict} · {instant(acceptance.recorded_at)}</p>}
        {acceptance.invalidated && <StateLabel warn>Acceptance invalidated</StateLabel>}
        {acceptance.authorized_proofs ? acceptance.authorized_proofs.map(proof => <p key={proof.proof_id} className="text-xs text-gray-400 break-all">Protected check: {proof.recipe} · {proof.proof_id}</p>)
          : <p className="text-xs text-gray-500">Protected proof details are unavailable for current access.</p>}
      </section>
      <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-3">
        <h3 className="font-semibold text-white">Permanent inherited allowance</h3>
        <div className="flex justify-between text-sm"><span className="text-gray-400">Allocated</span><span>{money(allowance.allocated_usd)}</span></div>
        <div className="flex justify-between text-sm"><span className="text-gray-400">Delegated</span><span>{money(allowance.delegated_usd)}</span></div>
        <div className="flex justify-between text-sm"><span className="text-gray-400">Held for this work</span><span>{money(allowance.own_ledger_held_usd)}</span></div>
        <div className="flex justify-between text-sm"><span className="text-gray-400">Actual cost for this work</span><span>{money(allowance.own_actual_total_usd)}</span></div>
        {allowance.own_billing_unconfirmed && <StateLabel warn>Billing unconfirmed; reservation retained</StateLabel>}
        <p className="text-xs text-gray-500">Model requests {allowance.consumed.model_requests}/{allowance.limits.model_requests} · Tool attempts {allowance.consumed.tool_attempts}/{allowance.limits.tool_attempts}</p>
      </section>
    </div>
    <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-3">
      <h3 className="font-semibold text-white">Issued results</h3>
      {data.receipts.length === 0 ? <p className="text-sm text-gray-400">No issued result in this page.</p> : data.receipts.map(receipt =>
        <div key={receipt.action_id} className="flex flex-wrap justify-between gap-2 text-sm border-t border-gray-800 pt-3">
          <span>{receipt.state.replace(/_/g, ' ')} · {receipt.billing}</span><span>{money(receipt.known_cost_usd)}</span></div>)}
    </section>
    {data.current_plan && <Link className="text-sm text-indigo-400" to={`/company/plans/${data.current_plan.plan_id}`}>Open current plan</Link>}
    <WorkCancellationPanel key={data.work.run_id} work={data} />
  </div>
}
