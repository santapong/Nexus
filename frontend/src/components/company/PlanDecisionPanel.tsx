import { useState } from 'react'
import { useCompanyDecision } from '@/hooks/useCompany'
import type { PlanView } from '@/types/company'
import { Button } from '@/components/ui/button'

export function PlanDecisionPanel({ plan, current, paused }: {
  plan: PlanView; current: PlanView; paused: boolean
}) {
  const [reviewed, setReviewed] = useState(false)
  const action = useCompanyDecision(plan.company_id)
  const approve = plan.state === 'proposed'
  const revoke = plan.state === 'approved' && plan.is_current_head
  if (!approve && !revoke) return null
  const submit = (kind: 'approve' | 'revoke') => action.mutate({ revision: plan.reference.plan_revision_id, kind,
    body: { exact_hash: plan.reference.sha256, expected_current_revision_id: current.reference.plan_revision_id } })
  return <section className="border border-indigo-600/30 bg-gray-900 rounded-lg p-5 space-y-4">
    <h3 className="font-semibold text-white">Owner decision</h3>
    <p className="text-sm text-gray-400">{approve ? 'Approve the actors, acceptance criteria and inherited allowances shown above.'
      : 'Revoke this exact current plan. Recorded costs and results remain in history.'}</p>
    <label className="flex gap-3 text-sm items-start text-gray-300">
      <input type="checkbox" className="mt-1 accent-indigo-500" checked={reviewed} onChange={event => setReviewed(event.target.checked)} />
      I reviewed this exact plan revision and its allowances.
    </label>
    <div className="text-xs font-mono text-gray-500 break-all">Manifest {plan.reference.sha256}</div>
    <Button variant={approve ? 'default' : 'destructive'} disabled={!reviewed || action.isPending || (approve && paused)}
      onClick={() => submit(approve ? 'approve' : 'revoke')}>{action.isPending ? 'Saving decision…' : approve ? 'Approve exact plan' : 'Revoke exact plan'}</Button>
    {paused && approve && <p className="text-sm text-amber-500">Company paused. Resume admission before approving new work.</p>}
    {action.isError && <p role="alert" className="text-sm text-red-400">{action.error.message} Refresh the plan before deciding again.</p>}
    {action.isSuccess && <p role="status" className="text-sm text-emerald-500">Owner decision recorded. No work was dispatched by this action.</p>}
  </section>
}
