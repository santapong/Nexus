import { useState } from 'react'
import type { PlanView } from '@/types/company'
import { useCompanyCommitment } from '@/hooks/useCompanyCommitment'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export function CommitmentForm({ plan, paused }: { plan: PlanView; paused: boolean }) {
  const [deliverable, setDeliverable] = useState('')
  const [responsible, setResponsible] = useState('')
  const [due, setDue] = useState('')
  const action = useCompanyCommitment(plan)
  return <form className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4"
    onSubmit={event => { event.preventDefault(); action.publish(deliverable, responsible, due) }}>
    <div><h3 className="font-semibold text-white">Record a commitment</h3>
      <p className="text-xs text-gray-400 mt-2">Describe the deliverable under this approved plan. A commitment does not record delivery or new spending authority.</p></div>
    <label className="block space-y-2 text-sm text-gray-300">Deliverable
      <Input value={deliverable} onChange={event => setDeliverable(event.target.value)} required maxLength={500} /></label>
    <label className="block space-y-2 text-sm text-gray-300">Responsible member
      <select className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-gray-100"
        value={responsible} onChange={event => setResponsible(event.target.value)} required>
        <option value="">Choose a responsible member</option>
        {[...new Set(plan.declaration.children.map(child => child.binding.actor_id))].map(actor => <option key={actor} value={actor}>Actor {actor}</option>)}
      </select></label>
    <label className="block space-y-2 text-sm text-gray-300">Due instant (your local timezone; optional)
      <Input type="datetime-local" value={due} onChange={event => setDue(event.target.value)} /></label>
    <p className="text-xs text-gray-500">Leave it blank when no actionable time has been chosen.</p>
    <Button type="submit" disabled={paused || action.mutation.isPending}>{action.mutation.isPending ? 'Recording…' : 'Record commitment'}</Button>
    {(action.error || action.mutation.isError) && <p role="alert" className="text-sm text-red-400">{action.error ?? action.mutation.error?.message}</p>}
    {action.mutation.isSuccess && <p role="status" className="text-sm text-emerald-500">Commitment recorded in current owner history.</p>}
  </form>
}
