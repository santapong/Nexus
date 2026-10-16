import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { CompanyApiError } from '@/api/company'
import { CompanyPlanningCandidate } from '@/components/company/CompanyPlanningCandidate'
import { CompanyQueryState, instant, StateLabel } from '@/components/company/CompanyStatus'
import { Button } from '@/components/ui/button'
import { canDispatchPlanning, canPreparePlanning, canRequestPlanningWaitRecovery, planningStage } from '@/hooks/companyPlanningState'
import { usePlanningBootstrap, usePlanningDispatch, usePlanningPrepare, usePlanningRecoverWait, usePlanningStatus } from '@/hooks/useCompanyPlanning'
import type { PlanningGoalSelection, PlanningLifecycleStatus } from '@/types/companyPlanning'

type Goal = PlanningGoalSelection['goal']

function DispatchPlanning({ status, paused, refreshing }: {
  status: PlanningLifecycleStatus; paused: boolean; refreshing: boolean
}) {
  const [confirmed, setConfirmed] = useState(false)
  const send = usePlanningDispatch(status.company_id, status.action_id ?? '')
  const hash = status.proposal_sha256
  if (!status.action_id || !hash || status.workflow_id) return null
  return <div className="space-y-3">
    <p className="text-sm text-gray-400">The exact input decision is saved. Dispatch sends that approved request to the registered worker.</p>
    <p className="text-xs text-gray-500">Decision expiry: {instant(status.owner_decision_expires_at)}</p>
    <label className="flex items-start gap-3 text-sm text-gray-300"><input type="checkbox" className="mt-1 accent-indigo-500"
      checked={confirmed} disabled={send.isPending || refreshing} onChange={event => setConfirmed(event.target.checked)} />
      Send the exact approved planning request.</label>
    <Button disabled={!confirmed || paused || refreshing || send.isPending || !canDispatchPlanning(status)}
      onClick={() => send.mutate(hash)}>{send.isPending ? 'Dispatching…' : 'Dispatch approved request'}</Button>
    {send.isError ? <p role="alert" className="text-sm text-red-400">{send.error.message} Inspect current status before another action.</p> : null}
    {send.isSuccess ? <p role="status" className="text-sm text-gray-300">Dispatch recorded. Refresh to inspect the outcome.</p> : null}
  </div>
}

function RecoverPlanningWait({ status, selection, paused }: {
  status: PlanningLifecycleStatus; selection: PlanningGoalSelection; paused: boolean
}) {
  const recover = usePlanningRecoverWait(status.company_id, status.action_id ?? '')
  const navigate = useNavigate()
  const action = status.action_id, hash = status.proposal_sha256, head = selection.expected_current_revision_id
  if (!action || !hash || !head) return null
  return <div className="space-y-3 border-t border-gray-800 pt-4">
    <p className="text-sm text-gray-400">A saved request exists without an approval-wait state. Ask the server to check recovery.
      This does not rebuild input, extend its saved window, or send a model call.</p>
    <Button variant="outline" disabled={paused || recover.isPending}
      onClick={() => recover.mutate({ goal: selection.goal, expected_current_revision_id: head, expected_hash: hash }, {
        onSuccess: () => navigate(`/company/actions/${action}`),
      })}>{recover.isPending ? 'Checking saved request…' : 'Recover saved approval wait'}</Button>
    {recover.isError ? <p role="alert" className="text-sm text-red-400">{recover.error.message} Inspect current status; the saved input is retained.</p> : null}
  </div>
}

function GoalPlanningFlow({ goal, paused, allowDispatch }: { goal: Goal; paused: boolean; allowDispatch: boolean }) {
  const query = usePlanningStatus(goal.company_id, goal.goal_id)
  const bootstrap = usePlanningBootstrap(goal.company_id)
  const prepare = usePlanningPrepare(goal.company_id)
  const [inspect, setInspect] = useState(false)
  const navigate = useNavigate()
  if (query.isPending) return <CompanyQueryState pending error={null} />
  if (query.isError || !query.data) return <div className="space-y-3" role="status">
    <p className="text-sm text-gray-400">{query.error instanceof CompanyApiError && query.error.status === 404
      ? 'Planning is not configured in this profile.' : query.error?.message ?? 'Planning is unavailable.'}</p>
    <Button variant="outline" onClick={() => { void query.refetch() }}>Refresh planning status</Button></div>
  const status = query.data
  const sameGoal = status.company_id === goal.company_id && status.goal.revision_id === goal.revision_id
    && status.goal.sha256 === goal.sha256 && status.goal.goal_id === goal.goal_id
  const selection: PlanningGoalSelection = { goal, expected_current_revision_id: status.current?.plan_revision_id ?? null }
  const pending = bootstrap.isPending || prepare.isPending || query.isFetching
  const formal = status.formal_proposal
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><StateLabel>{planningStage(status)}</StateLabel>
      <Button variant="outline" onClick={() => { void query.refetch() }} disabled={query.isFetching}>Refresh status</Button></div>
    <p className="text-xs text-gray-500">Observed {instant(status.observed_at)}. A saved proposal, dispatch or model response does not complete company work.</p>
    {!sameGoal ? <p role="alert" className="text-sm text-amber-500">This saved goal has changed. Refresh company records before proceeding.</p> : null}
    {!status.bootstrap && !status.current ? <div className="space-y-3">
      <p className="text-sm text-gray-400">The server proposes a planning actor and a declared lifetime allowance. You review and approve it separately.</p>
      <Button disabled={paused || !sameGoal || pending} onClick={() => bootstrap.mutate(selection, {
        onSuccess: record => navigate(`/company/plans/${record.plan_id}`),
      })}>{bootstrap.isPending ? 'Saving proposal…' : 'Create planning-only proposal'}</Button></div> : null}
    {status.bootstrap ? <Link className="block text-sm text-indigo-400" to={`/company/plans/${status.bootstrap.plan_id}`}>
      Inspect planning-only proposal and owner decision</Link> : null}
    {canPreparePlanning(status) ? <div className="space-y-3">
      <p className="text-sm text-gray-400">Prepare the complete current model input for review. This does not send a model request.</p>
      <Button disabled={paused || !sameGoal || pending} onClick={() => prepare.mutate(selection, {
        onSuccess: record => navigate(`/company/actions/${record.action.proposal.action_id}`),
      })}>{prepare.isPending ? 'Preparing input…' : 'Prepare exact model request'}</Button></div> : null}
    {status.action_id ? <Link className="block text-sm text-indigo-400" to={`/company/actions/${status.action_id}`}>
      Inspect exact input and recorded owner decision</Link> : null}
    {allowDispatch && status.owner_decision === 'approved' && sameGoal ? <DispatchPlanning
      key={status.proposal_sha256} status={status} paused={paused} refreshing={query.isFetching} /> : null}
    {sameGoal && canRequestPlanningWaitRecovery(status) ? <RecoverPlanningWait
      key={status.proposal_sha256} status={status} selection={selection} paused={paused || query.isFetching} /> : null}
    {formal ? <Link className="block text-sm text-indigo-400" to={`/company/plans/${formal.plan_id}?revision=${formal.plan_revision_id}`}>
      Review formal proposal and its separate approval</Link> : null}
    {status.native_state === 'succeeded' && status.action_id ? <div className="space-y-4">
      <Button variant="outline" onClick={() => setInspect(value => !value)}>{inspect ? 'Close recorded draft' : 'Review recorded draft'}</Button>
      {inspect ? <CompanyPlanningCandidate key={`${status.action_id}:${selection.expected_current_revision_id}`}
        company={goal.company_id} action={status.action_id} selection={selection} paused={paused || !sameGoal}
        allowProposal={!formal} /> : null}
    </div> : null}
    {bootstrap.isError || prepare.isError ? <p role="alert" className="text-sm text-red-400">{bootstrap.error?.message ?? prepare.error?.message}
      {' '}Inspect current status; saved input and prior outcomes are retained.</p> : null}
  </div>
}

export function CompanyGoalPlanning({ goal, paused, initiallyOpen = false, allowDispatch = false }: {
  goal: Goal; paused: boolean; initiallyOpen?: boolean; allowDispatch?: boolean
}) {
  const [open, setOpen] = useState(initiallyOpen)
  return <section className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-4" aria-label="Supervised planning">
    <div className="flex flex-wrap justify-between items-center gap-3"><h3 className="font-semibold text-white">Supervised planning</h3>
      <Button variant="outline" onClick={() => setOpen(value => !value)}>{open ? 'Close planning controls' : 'Planning options'}</Button></div>
    {open ? <GoalPlanningFlow goal={goal} paused={paused} allowDispatch={allowDispatch} />
      : <p className="text-sm text-gray-400">Prepare, review and dispatch a planning request in separate owner-controlled steps.</p>}
  </section>
}
