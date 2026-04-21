import type {
  A2AToken,
  AgentConfig,
  AgentInfo,
  Approval,
  ApprovalRatesData,
  AuditEvent,
  AuditTimelineEntry,
  BillingRecord,
  BillingSummary,
  CostBreakdown,
  CreateA2ATokenResponse,
  CreateAgentRequest,
  CreateListingRequest,
  CreateTaskResponse,
  DeadLetterData,
  EvalRunResponse,
  EvalScoresResponse,
  FeedbackSignalRecord,
  HealthCheck,
  Invoice,
  LoginResponse,
  MarketplaceListing,
  PerformanceData,
  RegisterResponse,
  ResolveApprovalResponse,
  RotateA2ATokenResponse,
  SubmitTaskFeedbackRequest,
  SubmitTaskFeedbackResponse,
  Task,
  TaskReplay,
  Workspace,
} from '../types'

const API_URL = import.meta.env.VITE_API_URL || ''

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

export const api = {
  health: () => apiFetch<HealthCheck>('/health'),

  listTasks: (limit = 50) => apiFetch<Task[]>(`/api/tasks?limit=${limit}`),

  getTask: (id: string) => apiFetch<Task>(`/api/tasks/${id}`),

  createTask: (instruction: string) =>
    apiFetch<CreateTaskResponse>('/api/tasks', {
      method: 'POST',
      body: JSON.stringify({ instruction }),
    }),

  listApprovals: () => apiFetch<Approval[]>('/api/approvals'),

  resolveApproval: (id: string, approved: boolean) =>
    apiFetch<ResolveApprovalResponse>(`/api/approvals/${id}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ approved, resolved_by: 'human' }),
    }),

  listAgents: () => apiFetch<AgentInfo[]>('/api/agents'),

  // Analytics
  getPerformance: (period = '30d') =>
    apiFetch<PerformanceData>(`/api/analytics/performance?period=${period}`),

  getCosts: (period = '30d') =>
    apiFetch<CostBreakdown>(`/api/analytics/costs?period=${period}`),

  getDeadLetters: () =>
    apiFetch<DeadLetterData>('/api/analytics/dead-letters'),

  // Phase 9 Track 1 — approval rates from task_feedback
  getApprovalRates: (period = '30d') =>
    apiFetch<ApprovalRatesData>(`/api/analytics/approval-rates?period=${period}`),

  // Phase 9 Track 1 — dual-score feedback on tasks
  submitTaskFeedback: (taskId: string, payload: SubmitTaskFeedbackRequest) =>
    apiFetch<SubmitTaskFeedbackResponse>(`/api/feedback/tasks/${taskId}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  listTaskFeedback: (taskId: string) =>
    apiFetch<FeedbackSignalRecord[]>(`/api/feedback/tasks/${taskId}`),

  // Task replay
  getTaskReplay: (taskId: string) =>
    apiFetch<TaskReplay>(`/api/tasks/${taskId}/replay`),

  // Audit
  getAuditEvents: (params?: {
    event_type?: string
    agent_id?: string
    limit?: number
    offset?: number
  }) => {
    const query = new URLSearchParams()
    if (params?.event_type) query.set('event_type', params.event_type)
    if (params?.agent_id) query.set('agent_id', params.agent_id)
    if (params?.limit) query.set('limit', String(params.limit))
    if (params?.offset) query.set('offset', String(params.offset))
    const qs = query.toString()
    return apiFetch<AuditEvent[]>(`/api/audit${qs ? `?${qs}` : ''}`)
  },

  getTaskTimeline: (taskId: string) =>
    apiFetch<AuditTimelineEntry[]>(`/api/audit/${taskId}/timeline`),

  // Dead letter resolve
  resolveDeadLetter: (id: string) =>
    apiFetch<{ id: string; resolved: boolean }>(
      `/api/analytics/dead-letters/${id}/resolve`,
      { method: 'POST' }
    ),

  // Eval scoring
  getEvalScores: (period = '7d') =>
    apiFetch<EvalScoresResponse>(`/api/eval/scores?period=${period}`),

  triggerEvalRun: () =>
    apiFetch<EvalRunResponse>('/api/eval/run', { method: 'POST' }),

  // A2A tokens
  listA2ATokens: () => apiFetch<A2AToken[]>('/api/a2a-tokens'),

  createA2AToken: (name: string, allowedSkills: string[] = ['*']) =>
    apiFetch<CreateA2ATokenResponse>('/api/a2a-tokens', {
      method: 'POST',
      body: JSON.stringify({ name, allowed_skills: allowedSkills }),
    }),

  revokeA2AToken: (id: string) =>
    apiFetch<{ id: string; revoked: boolean }>(`/api/a2a-tokens/${id}`, {
      method: 'DELETE',
    }),

  rotateA2AToken: (id: string) =>
    apiFetch<RotateA2ATokenResponse>(`/api/a2a-tokens/${id}/rotate`, {
      method: 'POST',
    }),

  // Auth
  register: (email: string, password: string, displayName: string) =>
    apiFetch<RegisterResponse>('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, display_name: displayName }),
    }),

  login: (email: string, password: string) =>
    apiFetch<LoginResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  // Workspaces
  listWorkspaces: () => apiFetch<Workspace[]>('/api/workspaces'),

  createWorkspace: (name: string, slug: string) =>
    apiFetch<Workspace>('/api/workspaces', {
      method: 'POST',
      body: JSON.stringify({ name, slug }),
    }),

  // Marketplace
  listMarketplaceListings: (skill?: string, minRating?: number) => {
    const params = new URLSearchParams()
    if (skill) params.set('skill', skill)
    if (minRating) params.set('min_rating', String(minRating))
    const qs = params.toString()
    return apiFetch<MarketplaceListing[]>(`/api/marketplace${qs ? `?${qs}` : ''}`)
  },

  createListing: (data: CreateListingRequest) =>
    apiFetch<MarketplaceListing>('/api/marketplace', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  publishListing: (id: string) =>
    apiFetch<{ id: string; is_published: boolean }>(`/api/marketplace/${id}/publish`, {
      method: 'POST',
    }),

  submitReview: (listingId: string, rating: number, comment?: string) =>
    apiFetch<{ listing_id: string; review_submitted: boolean; new_rating: number }>(
      `/api/marketplace/${listingId}/review`,
      {
        method: 'POST',
        body: JSON.stringify({ rating, comment }),
      }
    ),

  // Billing
  getBillingSummary: (period = '30d') =>
    apiFetch<BillingSummary>(`/api/billing/summary?period=${period}`),

  getBillingRecords: (limit = 50) =>
    apiFetch<BillingRecord[]>(`/api/billing/records?limit=${limit}`),

  getInvoice: (period = '30d') =>
    apiFetch<Invoice>(`/api/billing/invoice?period=${period}`),

  // Agent Builder
  listAgentConfigs: () => apiFetch<AgentConfig[]>('/api/agent-builder'),

  createCustomAgent: (data: CreateAgentRequest) =>
    apiFetch<AgentConfig>('/api/agent-builder', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  activateAgent: (id: string) =>
    apiFetch<{ id: string; is_active: boolean }>(`/api/agent-builder/${id}/activate`, {
      method: 'POST',
    }),

  deactivateAgent: (id: string) =>
    apiFetch<{ id: string; is_active: boolean }>(`/api/agent-builder/${id}`, {
      method: 'DELETE',
    }),
}
