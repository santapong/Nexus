import type {
  AgentInfo,
  Approval,
  CreateTaskResponse,
  HealthCheck,
  ResolveApprovalResponse,
  Task,
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
}
