import { companyFetch } from '@/api/company'
import type { CodingCandidateReview, CodingDispatchRecord, CodingGoalSelection,
  CodingInputReview, CodingLifecycleStatus, PreparedCodingAction, RecoverCodingWaitRequest } from '@/types/companyCoding'

const base = (company: string) => `/api/v2/companies/${encodeURIComponent(company)}/coding`
const goalPath = (company: string, goal: string) => `${base(company)}/goals/${encodeURIComponent(goal)}`
const actionPath = (company: string, action: string) => `${base(company)}/actions/${encodeURIComponent(action)}`
const post = (body: unknown): RequestInit => ({ method: 'POST', cache: 'no-store', body: JSON.stringify(body) })

export const companyCodingApi = {
  input: (company: string, action: string) => companyFetch<CodingInputReview>(
    `${actionPath(company, action)}/input`, { method: 'GET', cache: 'no-store' }),
  status: (company: string, goal: string) => companyFetch<CodingLifecycleStatus>(
    `${goalPath(company, goal)}/status`, { method: 'GET', cache: 'no-store' }),
  prepare: (company: string, selection: CodingGoalSelection) => companyFetch<PreparedCodingAction>(
    `${goalPath(company, selection.goal.goal_id)}/prepare`, post(selection)),
  dispatch: (company: string, action: string, hash: string) => companyFetch<CodingDispatchRecord>(
    `${actionPath(company, action)}/dispatch`, post({ expected_hash: hash })),
  candidate: (company: string, action: string, head: string) => companyFetch<CodingCandidateReview>(
    `${actionPath(company, action)}/candidate?expected_current_revision_id=${encodeURIComponent(head)}`,
    { method: 'GET', cache: 'no-store' }),
  recoverWait: (company: string, action: string, selection: RecoverCodingWaitRequest) => companyFetch<PreparedCodingAction>(
    `${actionPath(company, action)}/recover-wait`, post(selection)),
}
