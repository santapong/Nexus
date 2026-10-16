import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCompanyIdentity, useCompanyView } from '@/hooks/useCompany'
import { useCreateCompanyGoal } from '@/hooks/useCompanyKnowledge'
import { goalAvailability, goalRequest } from '@/hooks/companyGoalDraft'
import type { CompanyIdentity, MaterializedEvidence } from '@/types/company'

export function CompanyGoalDraft({ identity, evidence, revalidating = false }: { identity: CompanyIdentity; evidence: MaterializedEvidence; revalidating?: boolean }) {
  const currentIdentity = useCompanyIdentity()
  const company = useCompanyView(identity.company_id)
  const create = useCreateCompanyGoal(identity.company_id)
  const [goalId] = useState(() => crypto.randomUUID())
  const [title, setTitle] = useState('')
  const [target, setTarget] = useState('1')
  const [due, setDue] = useState('')
  const [reason, setReason] = useState('No current measurement has been recorded.')
  const [validation, setValidation] = useState<string | null>(null)
  const blocked = company.data ? goalAvailability(identity, company.data, evidence, revalidating || currentIdentity.isFetching || company.isFetching) : 'Loading the current mandate…'
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!company.data || blocked || company.isError || currentIdentity.isError || create.isPending || create.isSuccess || create.isError) return
    setValidation(null)
    try { create.mutate(goalRequest(identity, company.data, evidence, goalId, { title, target, due, reason })) }
    catch (error) { setValidation(error instanceof Error ? error.message : 'Review the goal inputs.') }
  }
  if (create.isSuccess) return <section role="status" className="rounded-lg border border-emerald-800 bg-gray-900 p-5 space-y-3">
    <h3 className="font-semibold text-white">Goal saved</h3>
    <p className="text-sm text-gray-300">{create.data.definition.title}</p>
    <p className="text-sm text-gray-400">Your source citation is recorded. A plan and its approvals are separate; no work has started.</p>
    <Link to="/company/overview" className="text-sm text-indigo-400 underline">Review company goals</Link>
  </section>
  return <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
    <div><h3 className="font-semibold text-white">Create a goal from this citation</h3>
      <p className="text-sm text-gray-400 mt-2">Set a target for verified items. The citation explains the goal; it does not establish a measured baseline or completed work.</p></div>
    {evidence.freshness === 'unknown' && <p role="status" className="text-sm text-amber-400">Source freshness is unknown. Review the excerpt before saving; the baseline will remain unknown.</p>}
    {company.isError && <p role="alert" className="text-sm text-amber-400">Current mandate unavailable: {company.error.message}</p>}
    {blocked && <p role="status" className="text-sm text-amber-400">{blocked} Your draft can stay here while you review it.</p>}
    <form onSubmit={submit} className="space-y-4">
      <div><label htmlFor="goal-title" className="block text-sm text-gray-300 mb-2">Goal title</label>
        <Input id="goal-title" value={title} maxLength={128} required onChange={event => setTitle(event.target.value)} placeholder="What should Nexus improve?" /></div>
      <div className="grid sm:grid-cols-2 gap-4">
        <div><label htmlFor="goal-target" className="block text-sm text-gray-300 mb-2">Target verified items (at least)</label>
          <Input id="goal-target" value={target} inputMode="numeric" required onChange={event => setTarget(event.target.value)} /></div>
        <div><label htmlFor="goal-due" className="block text-sm text-gray-300 mb-2">Desired date (optional)</label>
          <Input id="goal-due" type="date" value={due} onChange={event => setDue(event.target.value)} /></div>
      </div>
      <div><label htmlFor="goal-baseline" className="block text-sm text-gray-300 mb-2">Why the baseline is unknown</label>
        <Input id="goal-baseline" value={reason} maxLength={128} required onChange={event => setReason(event.target.value)} /></div>
      {validation && <p role="alert" className="text-sm text-amber-400">{validation}</p>}
      {create.isError && <div role="alert" className="text-sm text-amber-400 space-y-2">
        <p>Saving was not confirmed: {create.error.message}</p>
        <p>Check current company records before submitting another goal.</p>
        <Link to="/company/overview" className="underline">Review company records</Link>
      </div>}
      <Button type="submit" disabled={Boolean(blocked) || company.isError || currentIdentity.isError || create.isPending || create.isError}>
        {create.isPending ? 'Saving goal…' : 'Save cited goal'}</Button>
    </form>
  </section>
}
