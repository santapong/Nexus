import { useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import { useCompanyToday } from '@/hooks/useCompany'
import type { CompanyIdentity } from '@/types/company'
import { CompanyBudgetPanel } from '@/components/company/CompanyBudgetPanel'
import { CompanyQueryState, instant, StateLabel } from '@/components/company/CompanyStatus'
import { CompanyPageNavigation } from '@/components/company/CompanyPageNavigation'

export function CompanyTodayPage() {
  const identity = useOutletContext<CompanyIdentity>()
  const [after, setAfter] = useState<string | null>(null)
  const query = useCompanyToday(identity.company_id, after)
  const data = query.data
  if (query.isPending || query.isError || !data) return <CompanyQueryState pending={query.isPending}
    error={query.error} refresh={() => { void query.refetch() }} />
  return <div className="space-y-6">
    <div><h2 className="text-2xl font-semibold text-white">Today</h2>
      <p className="text-gray-400 mt-1">Current commitments, owner decisions and retained allowances.</p></div>
    {data.paused && <div role="status" className="p-4 border border-amber-700/50 rounded-lg text-amber-500">Company paused. Current records remain available for review.</div>}
    <CompanyBudgetPanel budget={data.budget} />
    <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
      <h3 className="font-semibold text-white">Due and overdue commitments</h3>
      {data.due.length === 0 ? <p className="text-sm text-gray-400">No due or overdue commitments in this page.</p>
        : data.due.map(item => <div key={item.revision.revision_id} className="border-t border-gray-800 pt-4 space-y-2">
          <div className="flex flex-wrap justify-between gap-2"><Link className="text-indigo-400 hover:underline"
            to={`/company/plans/${item.revision.definition.plan.plan_id}`}>{item.revision.definition.deliverable}</Link>
            <StateLabel warn={item.binding_state !== 'current'}>{item.binding_state}</StateLabel></div>
          <p className="text-xs text-gray-400">{instant(item.revision.definition.due.actionable_at)}</p>
          <div className="flex flex-wrap gap-3">{item.revision.definition.work.map(work =>
            <Link key={work.task_id} to={`/company/work/${work.task_id}`} className="text-xs text-gray-400 underline">Review work {work.task_id.slice(0, 8)}</Link>)}</div>
        </div>)}
    </section>
    <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
      <div className="flex justify-between"><h3 className="font-semibold text-white">Owner decisions</h3>
        <Link className="text-sm text-indigo-400" to="/company/approvals">Review approvals</Link></div>
      {data.decisions.pending_plans.map(plan => <Link key={plan.plan_revision_id}
        className="block text-sm text-gray-300 hover:text-white border-t border-gray-800 pt-3"
        to={`/company/plans/${plan.plan_id}?revision=${plan.plan_revision_id}`}>Inspect proposed plan revision {plan.revision}</Link>)}
      {data.decisions.approvals.map(action => <Link to={`/company/actions/${action.action_id}`} key={action.action_id} className="block text-sm text-indigo-400">{action.tool} · {action.state.replace(/_/g, ' ')}</Link>)}
      {data.decisions.pending_plans.length === 0 && data.decisions.approvals.length === 0 && <p className="text-sm text-gray-400">No pending owner decisions in this page.</p>}
    </section>
    <CompanyPageNavigation after={after} onChange={setAfter} continuations={[
      { label: 'commitments', cursor: data.next_due_after_id },
      { label: 'actions', cursor: data.decisions.next_after_id },
      { label: 'plans', cursor: data.decisions.next_plan_after_id },
    ]} />
    <p className="text-xs text-gray-500">Observed {instant(data.observed_at)} · Refresh to recheck current permissions and state.</p>
  </div>
}
