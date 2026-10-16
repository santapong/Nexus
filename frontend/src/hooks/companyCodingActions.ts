import { companyApi, companySessionVersion } from '@/api/company'
import { companyCodingApi } from '@/api/companyCoding'
import { canDecideCoding, canDispatchCoding, requireCodingInputReview } from '@/hooks/companyCodingState'
import type { CodingGoalSelection } from '@/types/companyCoding'

export async function decideCoding(company: string, action: string, proposalHash: string,
  headerHash: string, approved: boolean) {
  const session = companySessionVersion()
  const [review, input] = await Promise.all([companyApi.review(company, action), companyCodingApi.input(company, action)])
  if (session !== companySessionVersion()) throw new Error('Company session changed. Refresh before deciding.')
  requireCodingInputReview(input, review, company, action, proposalHash, headerHash)
  if (!canDecideCoding(review, false) || !review.detail) throw new Error('This coding action has changed or already has a decision.')
  return companyApi.actionDecision(company, review.detail.task_id, action, {
    schema_version: 'nexus.company.api.v1', trace_id: review.detail.trace_id, expected_hash: proposalHash, approved,
  })
}

export async function dispatchCoding(company: string, action: string, hash: string, selection: CodingGoalSelection) {
  const session = companySessionVersion()
  const [status, review] = await Promise.all([companyCodingApi.status(company, selection.goal.goal_id), companyApi.review(company, action)])
  if (session !== companySessionVersion()) throw new Error('Company session changed. Refresh before dispatching.')
  if (!canDispatchCoding(status, review) || status.action_id !== action || status.proposal_sha256 !== hash
    || status.current?.plan_revision_id !== selection.expected_current_revision_id
    || status.goal.company_id !== company || selection.goal.company_id !== company
    || status.goal.goal_id !== selection.goal.goal_id || status.goal.revision_id !== selection.goal.revision_id
    || status.goal.sha256 !== selection.goal.sha256) throw new Error('Coding status or approval changed. Inspect the current record before dispatch.')
  return companyCodingApi.dispatch(company, action, hash)
}
