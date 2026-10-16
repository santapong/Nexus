import { companyFetch } from '@/api/company'
import type { PlanRevision } from '@/types/company'
import type { PlanningCandidateReview, PlanningDispatchRecord, PlanningGoalSelection,
  PlanningInputReview, PlanningLifecycleStatus, PreparedPlanningAction,
  RecoverPlanningWaitRequest } from '@/types/companyPlanning'

const base = (company: string) => `/api/v2/companies/${encodeURIComponent(company)}/planning`
const goalPath = (company: string, goal: string) => `${base(company)}/goals/${encodeURIComponent(goal)}`
const actionPath = (company: string, action: string) => `${base(company)}/actions/${encodeURIComponent(action)}`
const post = (body: unknown): RequestInit => ({ method: 'POST', cache: 'no-store', body: JSON.stringify(body) })

export const companyPlanningApi = {
  input: (company: string, action: string) => companyFetch<PlanningInputReview>(
    `${actionPath(company, action)}/input`,
    { method: 'GET', cache: 'no-store' }),
  status: (company: string, goal: string) => companyFetch<PlanningLifecycleStatus>(
    `${goalPath(company, goal)}/status`, { method: 'GET', cache: 'no-store' }),
  bootstrap: (company: string, body: PlanningGoalSelection) => companyFetch<PlanRevision>(
    `${goalPath(company, body.goal.goal_id)}/bootstrap`, post(body)),
  prepare: (company: string, body: PlanningGoalSelection) => companyFetch<PreparedPlanningAction>(
    `${goalPath(company, body.goal.goal_id)}/prepare`, post(body)),
  dispatch: (company: string, action: string, expectedHash: string) => companyFetch<PlanningDispatchRecord>(
    `${actionPath(company, action)}/dispatch`, post({ expected_hash: expectedHash })),
  candidate: (company: string, action: string, expectedHead: string) => companyFetch<PlanningCandidateReview>(
    `${actionPath(company, action)}/candidate?expected_current_revision_id=${encodeURIComponent(expectedHead)}`,
    { method: 'GET', cache: 'no-store' }),
  propose: (company: string, action: string, body: PlanningGoalSelection) => companyFetch<PlanRevision>(
    `${actionPath(company, action)}/proposal`, post(body)),
  recoverWait: (company: string, action: string, body: RecoverPlanningWaitRequest) => companyFetch<PreparedPlanningAction>(
    `${actionPath(company, action)}/recover-wait`, post(body)),
}
