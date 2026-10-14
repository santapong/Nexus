import type {
  ApprovalPage, CommitmentPublish, CommitmentRevision, CompanyIdentity, CompanyView,
  PlanDecision, PlanRevision, PlanView, TodayView, WorkView,
  ActionReview, ActionDecision, ActionDecisionResponse,
  CompanyLogin, CompanySignup, CompanySession,
  ManagementControlDescriptor, WorkCancellationIntent, OwnerCancellation, CompanyPauseState,
} from '@/types/company'

const API_URL = import.meta.env.VITE_API_URL || ''
let sessionVersion = 0

export function companySessionVersion() { return sessionVersion }

export function setCompanySessionToken(token: string | null) {
  sessionVersion += 1
  if (token === null) localStorage.removeItem('nexus_token')
  else localStorage.setItem('nexus_token', token)
}

export class CompanyApiError extends Error {
  constructor(public readonly status: number, detail: string) { super(detail) }
}

export async function companyFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem('nexus_token')
  const version = sessionVersion
  const headers = new Headers(init?.headers)
  headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`${API_URL}${path}`, { ...init, headers })
  const current = () => {
    if (version !== sessionVersion || token !== localStorage.getItem('nexus_token')) {
      throw new CompanyApiError(409, 'Company session changed. Refresh with your current account.')
    }
  }
  current()
  if (!response.ok) {
    let detail = `Company request unavailable (${response.status})`
    try {
      const body: unknown = await response.json()
      if (typeof body === 'object' && body !== null && 'detail' in body && typeof body.detail === 'string') {
        detail = body.detail
      }
    } catch { /* HTTP status remains the authoritative failure state. */ }
    current()
    throw new CompanyApiError(response.status, detail)
  }
  const body = await response.json() as T
  current()
  return body
}

const base = (id: string) => `/api/v2/companies/${encodeURIComponent(id)}/management`
const query = (after?: string | null) => after ? `?after_id=${encodeURIComponent(after)}` : ''

export const companyApi = {
  controls: (id: string) => companyFetch<ManagementControlDescriptor>(base(id) + '/control'),
  pause: (id: string, paused: boolean) => companyFetch<CompanyPauseState>(
    `/api/v2/companies/${encodeURIComponent(id)}/pause`,
    { method: 'POST', body: JSON.stringify({ paused }) }),
  cancelWork: (id: string, body: WorkCancellationIntent) => companyFetch<OwnerCancellation>(
    `${base(id)}/control/work/${encodeURIComponent(body.command.target.task_id)}/cancel`,
    { method: 'POST', body: JSON.stringify(body) }),
  login: (body: CompanyLogin) => companyFetch<CompanySession>('/api/v2/company-session/login',
    { method: 'POST', body: JSON.stringify(body) }),
  signup: (body: CompanySignup) => companyFetch<CompanySession>('/api/v2/company-session/signup',
    { method: 'POST', body: JSON.stringify(body) }),
  identity: () => companyFetch<CompanyIdentity>('/api/v2/company'),
  company: (id: string, after?: string | null) => companyFetch<CompanyView>(base(id) + '/company' + query(after)),
  today: (id: string, after?: string | null) => companyFetch<TodayView>(base(id) + '/today' + query(after)),
  approvals: (id: string, after?: string | null) => companyFetch<ApprovalPage>(base(id) + '/approvals' + query(after)),
  plan: (id: string, planId: string, revision?: string | null) => companyFetch<PlanView>(
    `${base(id)}/plans/${encodeURIComponent(planId)}${revision ? `?revision_id=${encodeURIComponent(revision)}` : ''}`),
  work: (id: string, task: string) => companyFetch<WorkView>(`${base(id)}/work/${encodeURIComponent(task)}`),
  decision: (id: string, revision: string, kind: 'approve' | 'revoke', body: PlanDecision) =>
    companyFetch<PlanRevision>(`${base(id)}/plans/${encodeURIComponent(revision)}/${kind}`,
      { method: 'POST', body: JSON.stringify(body) }),
  publishCommitment: (id: string, body: CommitmentPublish) => companyFetch<CommitmentRevision>(base(id) + '/commitments',
    { method: 'POST', body: JSON.stringify(body) }),
  review: (id: string, action: string) => companyFetch<ActionReview>(`${base(id)}/actions/${encodeURIComponent(action)}/review`),
  actionDecision: (id: string, task: string, action: string, body: ActionDecision) =>
    companyFetch<ActionDecisionResponse>(`/api/v2/companies/${encodeURIComponent(id)}/work/${encodeURIComponent(task)}/actions/${encodeURIComponent(action)}/decision`,
      { method: 'POST', body: JSON.stringify(body) }),
}
