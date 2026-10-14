import { Link, useOutletContext, useParams, useSearchParams } from 'react-router-dom'
import { useCompanyPlan, useCompanyView } from '@/hooks/useCompany'
import type { CompanyIdentity } from '@/types/company'
import { CompanyQueryState, money, StateLabel } from '@/components/company/CompanyStatus'
import { PlanDecisionPanel } from '@/components/company/PlanDecisionPanel'
import { CommitmentForm } from '@/components/company/CommitmentForm'

export function CompanyPlanPage() {
  const identity = useOutletContext<CompanyIdentity>()
  const { planId } = useParams()
  const [search] = useSearchParams()
  const query = useCompanyPlan(identity.company_id, planId, search.get('revision'))
  const current = useCompanyPlan(identity.company_id, planId)
  const company = useCompanyView(identity.company_id)
  if (query.isPending || current.isPending || company.isPending || query.isError || current.isError || company.isError)
    return <CompanyQueryState pending={query.isPending || current.isPending || company.isPending}
      error={query.error ?? current.error ?? company.error} refresh={() => { void query.refetch(); void current.refetch(); void company.refetch() }} />
  const data = query.data
  if (!data || !current.data || !company.data) return null
  const declaration = data.declaration
  return <div className="space-y-5">
    <div className="flex flex-wrap gap-3 justify-between"><div><h2 className="text-2xl font-semibold text-white">Plan revision {data.reference.revision}</h2>
      <p className="text-xs text-gray-500 font-mono break-all mt-2">{data.reference.plan_id}</p></div>
      <div className="flex gap-2"><StateLabel>{data.state}</StateLabel><StateLabel>{data.is_current_head ? 'Current head' : 'Inspected revision'}</StateLabel></div></div>
    <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-3">
      <h3 className="font-semibold text-white">Inherited plan allowance</h3>
      <p className="text-lg text-white">{money(declaration.procedure.allocation_usd)}</p>
      <p className="text-xs text-gray-400">Original lifetime allocation · Model requests {declaration.procedure.quota.model_requests} · Tool attempts {declaration.procedure.quota.tool_attempts}</p>
      <p className="text-xs text-gray-500">Approving a revision preserves the existing parent allowance and counters.</p>
    </section>
    <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
      <h3 className="font-semibold text-white">Declared work and acceptance</h3>
      {declaration.plan.items.map(item => {
        const allocation = declaration.children.find(child => child.binding.task_id === item.task_id)
        return <div key={item.task_id} className="border-t border-gray-800 pt-4 space-y-2">
          <p className="font-medium text-gray-200">{item.title}</p><p className="text-xs text-gray-400">{item.department} · {money(allocation?.allocation_usd)} inherited slice</p>
          <p className="text-xs text-gray-500 font-mono break-all">Actor {allocation?.binding.actor_id}</p>
          <ul className="text-sm text-gray-400 list-disc pl-5">{item.acceptance.map(criterion => <li key={criterion}>{criterion}</li>)}</ul>
          {data.work.some(work => work.work.task_id === item.task_id) && <Link className="text-xs text-indigo-400" to={`/company/work/${item.task_id}`}>Inspect native work</Link>}
        </div>
      })}
    </section>
    <details className="rounded-lg border border-gray-800 bg-gray-900 p-5">
      <summary className="cursor-pointer text-sm font-medium text-gray-200">Complete exact plan declaration</summary>
      <pre className="mt-4 text-xs text-gray-400 whitespace-pre-wrap break-all overflow-auto" aria-label="Exact plan declaration">
        {JSON.stringify(declaration, null, 2)}</pre>
    </details>
    <PlanDecisionPanel key={data.reference.sha256} plan={data} current={current.data} paused={company.data.paused} />
    {data.state === 'approved' && data.is_current_head && <CommitmentForm key={data.reference.sha256} plan={data} paused={company.data.paused} />}
  </div>
}
