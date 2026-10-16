import { companyApi, companySessionVersion } from '@/api/company'
import { companyPlanningApi } from '@/api/companyPlanning'
import { canDecidePlanning, requirePlanningInputReview } from '@/hooks/companyPlanningState'

export async function decidePlanning(company: string, action: string, proposalHash: string,
  descriptorHash: string, approved: boolean) {
  const session = companySessionVersion()
  const [review, input] = await Promise.all([
    companyApi.review(company, action), companyPlanningApi.input(company, action),
  ])
  if (session !== companySessionVersion()) throw new Error('Company session changed. Refresh before deciding.')
  requirePlanningInputReview(input, review, company, action, proposalHash, descriptorHash)
  if (!canDecidePlanning(review, false) || !review.detail) {
    throw new Error('This planning action has changed or already has a decision. Refresh its record.')
  }
  return companyApi.actionDecision(company, review.detail.task_id, action, {
    schema_version: 'nexus.company.api.v1', trace_id: review.detail.trace_id,
    expected_hash: proposalHash, approved,
  })
}
