import { CompanyQueryState, instant } from '@/components/company/CompanyStatus'
import { useCodingCandidate } from '@/hooks/useCompanyCoding'
import type { CodingCandidateReview, CodingGoalSelection } from '@/types/companyCoding'

export function CodingCandidateContent({ data }: { data: CodingCandidateReview }) {
  return <section className="space-y-4" aria-label="Recorded coding candidate">
    <h4 className="font-semibold text-white">Recorded code proposal</h4>
    <p className="text-sm text-gray-400">Model output recorded {instant(data.recorded_at)}. Building and independent verification remain separate steps.</p>
    <p className="text-sm text-gray-300 whitespace-pre-wrap">{data.content.explanation}</p>
    <pre aria-label="Proposed patch" className="max-h-96 overflow-auto rounded-lg border border-gray-800 bg-gray-950 p-4 text-xs text-gray-300 whitespace-pre-wrap break-words">{data.content.patch}</pre>
    {data.content.questions.length > 0 ? <div><h5 className="text-sm font-medium text-amber-500">Questions and limitations</h5>
      <ul className="list-disc pl-5 text-sm text-gray-400">{data.content.questions.map(question => <li key={question}>{question}</li>)}</ul></div> : null}
    <details className="text-xs text-gray-500"><summary className="cursor-pointer">Recorded provenance</summary>
      <div className="mt-3 font-mono break-all space-y-2"><p>Receipt {data.receipt_id}</p><p>Artifact {data.artifact_sha256}</p></div></details>
  </section>
}

export function CompanyCodingCandidate({ company, action, selection }: {
  company: string; action: string; selection: CodingGoalSelection
}) {
  const query = useCodingCandidate(company, action, selection.expected_current_revision_id)
  if (query.isPending || query.isError || !query.data) return <CompanyQueryState pending={query.isPending}
    error={query.error} refresh={() => { void query.refetch() }} />
  const data = query.data, goal = data.binding.goal
  if (data.company_id !== company || data.action_id !== action || data.historical !== true
    || data.company_completed !== false || goal.company_id !== company
    || goal.goal_id !== selection.goal.goal_id || goal.revision_id !== selection.goal.revision_id
    || goal.sha256 !== selection.goal.sha256
    || data.binding.plan.plan_revision_id !== selection.expected_current_revision_id) {
    return <CompanyQueryState pending={false} error={new Error('The recorded patch belongs to a different goal or plan. Refresh its record.')} />
  }
  return <CodingCandidateContent data={data} />
}
