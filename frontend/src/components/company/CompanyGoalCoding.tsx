import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { companySessionVersion } from '@/api/company'
import { CompanyCodingCandidate } from '@/components/company/CompanyCodingCandidate'
import { CompanyQueryState, instant, StateLabel } from '@/components/company/CompanyStatus'
import { Button } from '@/components/ui/button'
import { useActionReview } from '@/hooks/useCompany'
import { canDispatchCoding, canPrepareCoding, canRecoverCodingWait, codingStage } from '@/hooks/companyCodingState'
import { useCodingDispatch, useCodingPrepare, useCodingRecovery, useCodingStatus } from '@/hooks/useCompanyCoding'
import type { CodingGoalSelection, CodingLifecycleStatus } from '@/types/companyCoding'

type Goal = CodingGoalSelection['goal']

function CodingActionControls({ status, selection, paused }: {
  status: CodingLifecycleStatus; selection: CodingGoalSelection; paused: boolean
}) {
  const review = useActionReview(status.company_id, status.action_id ?? undefined)
  const dispatch = useCodingDispatch(status.company_id, status.action_id ?? '')
  const recovery = useCodingRecovery(status.company_id, status.action_id ?? '')
  const [checked, setChecked] = useState(false)
  if (!status.action_id || !status.proposal_sha256) return null
  if (review.isPending || review.isError || !review.data) return <CompanyQueryState pending={review.isPending}
    error={review.error} refresh={() => { void review.refetch() }} />
  const allowed = canDispatchCoding(status, review.data)
  const pending = paused || review.isFetching || dispatch.isPending || recovery.isPending
  return <div className="space-y-4">
    <Link className="block text-sm text-indigo-400 underline" to={`/company/actions/${status.action_id}`}>Inspect exact coding input and decision</Link>
    {allowed ? <div className="space-y-3">
      <p className="text-sm text-gray-400">The exact owner decision is saved. Dispatch sends this request to the registered coding worker.</p>
      <label className="flex items-start gap-3 text-sm text-gray-300"><input type="checkbox" className="mt-1 accent-indigo-500"
        checked={checked} disabled={pending} onChange={event => setChecked(event.target.checked)} />Send this exact approved coding request.</label>
      <Button disabled={!checked || pending} onClick={() => dispatch.mutate({ hash: status.proposal_sha256!, selection })}>
        {dispatch.isPending ? 'Dispatching…' : 'Dispatch approved coding request'}</Button>
    </div> : null}
    {canRecoverCodingWait(status, review.data) ? <div className="space-y-3">
      <p className="text-sm text-gray-400">A saved request needs its approval-wait state checked. Recovery preserves the saved input and original limits.</p>
      <Button variant="outline" disabled={pending} onClick={() => recovery.mutate({ ...selection, expected_hash: status.proposal_sha256! })}>
        {recovery.isPending ? 'Checking saved wait…' : 'Recover saved coding wait'}</Button>
    </div> : null}
    {dispatch.isError || recovery.isError ? <p role="alert" className="text-sm text-red-400">{dispatch.error?.message ?? recovery.error?.message} Inspect current status before another action.</p> : null}
    {dispatch.isSuccess ? <p role="status" className="text-sm text-gray-300">Dispatch recorded. Refresh to inspect the outcome.</p> : null}
  </div>
}

function GoalCodingFlow({ goal, paused }: { goal: Goal; paused: boolean }) {
  const query = useCodingStatus(goal.company_id, goal.goal_id)
  const prepare = useCodingPrepare(goal.company_id)
  const [inspect, setInspect] = useState(false)
  const navigate = useNavigate()
  if (query.isPending || query.isError || !query.data) return <CompanyQueryState pending={query.isPending}
    error={query.error} refresh={() => { void query.refetch() }} />
  const status = query.data
  const same = status.company_id === goal.company_id && status.goal.goal_id === goal.goal_id
    && status.goal.revision_id === goal.revision_id && status.goal.sha256 === goal.sha256
  const head = status.current?.plan_revision_id
  const selection = head ? { goal, expected_current_revision_id: head } : null
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><StateLabel>{codingStage(status)}</StateLabel>
      <Button variant="outline" disabled={query.isFetching || prepare.isPending} onClick={() => { void query.refetch() }}>Refresh coding status</Button></div>
    <p className="text-xs text-gray-500">Observed {instant(status.observed_at)}. A model response does not complete company work.</p>
    {!same ? <p role="alert" className="text-sm text-amber-500">The current goal differs from this page. Refresh company records.</p> : null}
    {selection && canPrepareCoding(status) ? <div className="space-y-3">
      <p className="text-sm text-gray-400">Prepare the current source and exact model input for owner review.</p>
      <Button disabled={paused || !same || query.isFetching || prepare.isPending} onClick={() => prepare.mutate(selection, {
        onSuccess: value => navigate(`/company/actions/${value.action.proposal.action_id}`),
      })}>{prepare.isPending ? 'Preparing coding input…' : 'Prepare coding request'}</Button>
    </div> : null}
    {selection && status.action_id && same ? <CodingActionControls
      key={`${companySessionVersion()}:${status.action_id}:${status.proposal_sha256}`} status={status}
      selection={selection} paused={paused || query.isFetching} /> : null}
    {selection && status.action_id && same && status.native_state === 'succeeded' ? <div className="space-y-4">
      <Button variant="outline" onClick={() => setInspect(value => !value)}>{inspect ? 'Close recorded patch' : 'Inspect recorded patch'}</Button>
      {inspect ? <CompanyCodingCandidate key={`${status.action_id}:${head}`} company={goal.company_id}
        action={status.action_id} selection={selection} /> : null}
    </div> : null}
    {prepare.isError ? <p role="alert" className="text-sm text-red-400">{prepare.error.message} Inspect current status; prior input and outcomes remain recorded.</p> : null}
  </div>
}

export function CompanyGoalCoding({ goal, paused, initiallyOpen = false }: { goal: Goal; paused: boolean; initiallyOpen?: boolean }) {
  const [open, setOpen] = useState(initiallyOpen)
  return <section className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-4" aria-label="Supervised coding">
    <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold text-white">Supervised coding</h3>
      <Button variant="outline" onClick={() => setOpen(value => !value)}>{open ? 'Close coding controls' : 'Coding options'}</Button></div>
    {open ? <GoalCodingFlow goal={goal} paused={paused} />
      : <p className="text-sm text-gray-400">Prepare, review and dispatch a coding request after the operating plan is approved.</p>}
  </section>
}
