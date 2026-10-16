import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { CompanyQueryState, instant } from '@/components/company/CompanyStatus'
import { usePlanningCandidate, usePlanningProposal } from '@/hooks/useCompanyPlanning'
import type { PlanningCandidateReview, PlanningGoalSelection } from '@/types/companyPlanning'

export function PlanningCandidateContent({ data }: { data: PlanningCandidateReview }) {
  return <section className="space-y-4" aria-label="Recorded planning draft">
    <div><h4 className="font-semibold text-white">Recorded planning draft</h4>
      <p className="text-sm text-gray-400 mt-2">Historical model output from {instant(data.model_recorded_at)}.
        This view does not approve a plan or complete any work.</p></div>
    {data.content.tasks.map(task => <article key={task.key} className="border-t border-gray-800 pt-4 space-y-2">
      <h5 className="font-medium text-gray-200">{task.title}</h5>
      <p className="text-sm text-gray-300 whitespace-pre-wrap">{task.description}</p>
      <ul className="list-disc pl-5 text-sm text-gray-400">{task.acceptance.map(item => <li key={item}>{item}</li>)}</ul>
      <p className="text-xs text-gray-500">Ordering: {task.depends_on.length ? task.depends_on.join(', ') : 'No additional ordering'}</p>
      <details className="text-xs text-gray-500"><summary className="cursor-pointer">Evidence references</summary>
        <ul className="mt-2 space-y-1 font-mono break-all">{task.evidence_ids.map(id => <li key={id}>{id}</li>)}</ul></details>
    </article>)}
    {data.content.questions.length ? <div className="space-y-2"><h5 className="font-medium text-gray-200">Questions and limitations</h5>
      <ul className="list-disc pl-5 text-sm text-gray-400">{data.content.questions.map(question => <li key={question}>{question}</li>)}</ul></div> : null}
    <details className="text-xs text-gray-500"><summary className="cursor-pointer">Recorded provenance</summary>
      <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify(data.origin, null, 2)}</pre></details>
  </section>
}

export function CompanyPlanningCandidate({ company, action, selection, paused, allowProposal = true }: {
  company: string; action: string; selection: PlanningGoalSelection; paused: boolean; allowProposal?: boolean
}) {
  const query = usePlanningCandidate(company, action, selection.expected_current_revision_id)
  const propose = usePlanningProposal(company, action)
  const [reviewed, setReviewed] = useState(false)
  const navigate = useNavigate()
  if (selection.expected_current_revision_id === null) return <p role="alert" className="text-sm text-amber-500">The current plan is unavailable. Refresh its record.</p>
  if (query.isPending || query.isError || !query.data) return <CompanyQueryState pending={query.isPending}
    error={query.error} refresh={() => { void query.refetch() }} />
  const data = query.data
  const matches = data.company_id === company && data.action_id === action
    && data.goal.goal_id === selection.goal.goal_id && data.goal.revision_id === selection.goal.revision_id
    && data.goal.sha256 === selection.goal.sha256
    && data.historical === true && data.company_completed === false
  const headMatches = data.bootstrap.plan_revision_id === selection.expected_current_revision_id
  return <div className="border-t border-gray-800 pt-5 space-y-4">
    <PlanningCandidateContent data={data} />
    {!matches ? <p role="alert" className="text-sm text-amber-500">The goal or plan has changed. Refresh before creating a proposal.</p> : null}
    {!allowProposal ? <p className="text-sm text-gray-400">A formal proposal is already recorded. Review its exact plan and separate owner decision.</p> : <>
    <p className="text-sm text-gray-400">The server maps this draft to the fixed actors, criteria and existing allowance.
      You will review and approve the resulting exact plan separately.</p>
    {!headMatches ? <p role="alert" className="text-sm text-amber-500">The plan head has changed. Refresh before creating a proposal.</p> : null}
    <label className="flex items-start gap-3 text-sm text-gray-300"><input type="checkbox" className="mt-1 accent-indigo-500"
      checked={reviewed} disabled={propose.isPending || query.isFetching}
      onChange={event => setReviewed(event.target.checked)} />I reviewed this recorded draft and its questions.</label>
    <Button disabled={!reviewed || !matches || !headMatches || paused || query.isFetching || propose.isPending}
      onClick={() => propose.mutate(selection, { onSuccess: record => navigate(`/company/plans/${record.plan_id}`) })}>
      {propose.isPending ? 'Saving proposal…' : 'Create formal plan proposal'}</Button>
    </>}
    {propose.isError ? <p role="alert" className="text-sm text-red-400">{propose.error.message} The draft remains recorded.</p> : null}
  </div>
}
