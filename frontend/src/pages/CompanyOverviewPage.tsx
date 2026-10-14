import { useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import { useCompanyView } from '@/hooks/useCompany'
import type { CompanyIdentity } from '@/types/company'
import { CompanyBudgetPanel } from '@/components/company/CompanyBudgetPanel'
import { CompanyQueryState, instant, StateLabel } from '@/components/company/CompanyStatus'
import { CompanyPageNavigation } from '@/components/company/CompanyPageNavigation'
import { CompanyPausePanel } from '@/components/company/CompanyPausePanel'

export function CompanyOverviewPage() {
  const identity = useOutletContext<CompanyIdentity>()
  const [after, setAfter] = useState<string | null>(null)
  const query = useCompanyView(identity.company_id, after)
  const data = query.data
  if (query.isPending || query.isError || !data) return <CompanyQueryState pending={query.isPending}
    error={query.error} refresh={() => { void query.refetch() }} />
  return <div className="space-y-6">
    <div className="flex flex-wrap gap-3 justify-between"><div><h2 className="text-2xl font-semibold text-white">Company</h2>
      <p className="text-gray-400 mt-2">{data.mandate?.revision.mandate.purpose ?? 'No current mandate recorded.'}</p></div>
      <StateLabel warn={data.paused}>{data.paused ? 'Paused' : 'Owner supervised'}</StateLabel></div>
    <CompanyBudgetPanel budget={data.budget} />
    <CompanyPausePanel key={identity.company_id} companyId={identity.company_id} paused={data.paused} />
    <div className="grid md:grid-cols-2 gap-5">
      <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
        <h3 className="font-semibold text-white">Goals</h3>
        {data.goals.map(goal => <div key={goal.reference.revision_id} className="border-t border-gray-800 pt-4 space-y-2">
          <div className="flex justify-between gap-3"><p className="font-medium text-gray-200">{goal.title}</p>
            <StateLabel warn={!goal.active}>{goal.active ? 'Active' : 'Inactive'}</StateLabel></div>
          {goal.metrics.map(metric => <div key={metric.metric_id} className="text-sm text-gray-400">
            <p>{metric.metric_id} · Target {metric.comparator} {metric.target} {metric.unit}</p>
            <p className="text-xs mt-1">{metric.baseline?.kind === 'known' ? `Recorded baseline ${metric.baseline.value}`
              : metric.baseline?.kind === 'unknown' ? metric.baseline.reason : 'Baseline unavailable for current access'}</p></div>)}
          <p className="text-xs text-gray-500">{instant(goal.due.actionable_at)}</p>
        </div>)}
        {data.goals.length === 0 && <p className="text-sm text-gray-400">No goals in this page.</p>}
      </section>
      <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
        <h3 className="font-semibold text-white">Approved and proposed plans</h3>
        {data.plans.map(plan => <Link key={plan.reference.plan_revision_id}
          to={`/company/plans/${plan.reference.plan_id}`} className="block border-t border-gray-800 pt-4 hover:text-indigo-400">
          <div className="flex justify-between gap-3"><span className="text-sm">Plan revision {plan.reference.revision}</span>
            <StateLabel warn={plan.state !== 'approved'}>{plan.state}</StateLabel></div>
          <p className="text-xs text-gray-500 mt-2 font-mono">{plan.reference.plan_id}</p></Link>)}
        {data.plans.length === 0 && <p className="text-sm text-gray-400">No plans in this page.</p>}
      </section>
    </div>
    <section className="rounded-lg border border-gray-800 bg-gray-900 p-5">
      <h3 className="font-semibold text-white mb-4">Departments</h3>
      <div className="grid sm:grid-cols-2 gap-4">{data.charters.map(charter => <div key={charter.revision.revision_id}>
        <div className="flex items-center gap-2"><p className="text-gray-200">{charter.revision.charter.name}</p>
          <StateLabel warn={!charter.active}>{charter.active ? 'Active' : 'Inactive'}</StateLabel></div>
        <p className="text-xs text-gray-400 mt-2">{charter.revision.charter.responsibilities.join(' · ')}</p></div>)}</div>
    </section>
    <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-3">
      <h3 className="font-semibold text-white">Commitments</h3>
      {data.commitments.map(item => <div key={item.revision.revision_id} className="flex flex-wrap gap-2 justify-between border-t border-gray-800 pt-3">
        <Link to={`/company/plans/${item.revision.definition.plan.plan_id}`} className="text-sm text-indigo-400">{item.revision.definition.deliverable}</Link>
        <StateLabel warn={item.binding_state !== 'current'}>{item.binding_state}</StateLabel>
        <span className="text-xs text-gray-400">{instant(item.revision.definition.due.actionable_at)}</span></div>)}
      {data.commitments.length === 0 && <p className="text-sm text-gray-400">No commitments in this page. Open an approved plan to record one.</p>}
    </section>
    <CompanyPageNavigation after={after} onChange={setAfter} continuations={[
      { label: 'goals', cursor: data.next_goal_after_id },
      { label: 'plans', cursor: data.next_plan_after_id },
      { label: 'departments', cursor: data.next_charter_after_id },
      { label: 'commitments', cursor: data.next_commitment_after_id },
    ]} />
  </div>
}
