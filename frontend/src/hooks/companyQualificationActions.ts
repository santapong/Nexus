import { companyApi } from '@/api/company'
import { companyQualificationApi } from '@/api/companyQualification'
import { canDecideQualification, canDispatchQualification, requireQualificationReview } from '@/hooks/companyQualificationState'

export async function decideQualification(company: string, action: string, hash: string, approved: boolean) {
  const status = await companyQualificationApi.status(company, action)
  requireQualificationReview(status, company, action, hash)
  if (!canDecideQualification(status, false, approved)) {
    throw new Error('This check has changed or cannot accept another decision. Refresh its current record.')
  }
  return companyApi.actionDecision(company, status.action.proposal.task_id, action, {
    schema_version: 'nexus.company.api.v1', trace_id: status.action.proposal.trace_id,
    expected_hash: hash, approved,
  })
}

export async function dispatchQualification(company: string, action: string, hash: string) {
  const status = await companyQualificationApi.status(company, action)
  requireQualificationReview(status, company, action, hash)
  if (!canDispatchQualification(status, false)) {
    throw new Error('This check cannot dispatch from its current state. Refresh the approval and usage record.')
  }
  return companyQualificationApi.dispatch(company, action, hash)
}
