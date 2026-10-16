import { useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import { useCompanyApprovals } from '@/hooks/useCompany'
import type { CompanyIdentity } from '@/types/company'
import { CompanyQueryState, instant, money, StateLabel } from '@/components/company/CompanyStatus'
import { CompanyPageNavigation } from '@/components/company/CompanyPageNavigation'

export function CompanyApprovalsPage() {
  const identity = useOutletContext<CompanyIdentity>()
  const [after, setAfter] = useState<string | null>(null)
  const query = useCompanyApprovals(identity.company_id, after)
  const data = query.data
  if (query.isPending || query.isError || !data) return <CompanyQueryState pending={query.isPending}
    error={query.error} refresh={() => { void query.refetch() }} />
  return <div className="space-y-5">
    <div><h2 className="text-2xl font-semibold text-white">Approvals</h2>
      <p className="text-gray-400 mt-2">Exact proposals and recorded owner decisions. Routine work retains its approved limits.</p></div>
    <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
      <h3 className="font-semibold text-white">Plans awaiting a decision</h3>
      {data.pending_plans.length === 0 && <p className="text-sm text-gray-400">No pending plan in this page.</p>}
      {data.pending_plans.map(plan => <Link key={plan.plan_revision_id}
        to={`/company/plans/${plan.plan_id}?revision=${plan.plan_revision_id}`} className="block border-t border-gray-800 pt-4">
        <p className="text-indigo-400">Inspect plan revision {plan.revision}</p>
        <p className="text-xs text-gray-400 mt-1">Inherited allocation {money(plan.payload.procedure.allocation_usd)}</p>
        <p className="text-xs text-gray-500 font-mono break-all mt-2">Manifest {plan.sha256}</p></Link>)}
    </section>
    <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
      <h3 className="font-semibold text-white">Action decisions and authority history</h3>
      {data.approvals.length === 0 && <p className="text-sm text-gray-400">No action decision in this page.</p>}
      {data.approvals.map(action => <div key={action.action_id} className="border-t border-gray-800 pt-4 space-y-2">
        <div className="flex flex-wrap justify-between gap-2"><p className="font-medium text-gray-200">{action.tool}</p><StateLabel>{action.state.replace(/_/g, ' ')}</StateLabel></div>
        <p className="text-sm text-gray-400">{action.resource_symbol} · Estimated {money(action.estimated_cost_usd)}</p>
        <p className="text-xs text-gray-500">{action.authority_observation.replace(/_/g, ' ')}{action.owner_decision && ` · ${action.owner_decision.decision} · expires ${instant(action.owner_decision.expires_at)}`}</p>
        <p className="text-xs text-gray-500 font-mono break-all">Exact proposal {action.proposal_sha256}</p>
        {action.tool !== 'model.qualify.v1' && <Link className="text-xs text-indigo-400" to={`/company/work/${action.task_id}`}>Inspect work and costs</Link>}
        <Link className="block text-sm text-indigo-400" to={action.tool === 'model.qualify.v1'
          ? `/company/model-checks/actions/${action.action_id}` : `/company/actions/${action.action_id}`}>Review exact action</Link>
      </div>)}
    </section>
    <CompanyPageNavigation after={after} onChange={setAfter} continuations={[
      { label: 'actions', cursor: data.next_after_id },
      { label: 'plans', cursor: data.next_plan_after_id },
    ]} />
  </div>
}
