import type {
  AgentInfo,
  Approval,
  AuditEvent,
  AuditTimelineEntry,
  CostBreakdown,
  CreateTaskResponse,
  DeadLetterData,
  HealthCheck,
  PerformanceData,
  ResolveApprovalResponse,
  Task,
  TaskReplay,
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
}
