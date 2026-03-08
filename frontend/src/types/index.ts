export interface HealthCheck {
  status: string
  checks: Record<string, string>
}

export interface Task {
  id: string
  trace_id: string
  instruction: string
  status: string
  source: string
  tokens_used: number
  output: Record<string, unknown> | null
  error: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface CreateTaskResponse {
  task_id: string
  trace_id: string
  status: string
}

export interface Approval {
  id: string
  task_id: string
  agent_id: string
  tool_name: string
  action_description: string
  status: string
  requested_at: string
  resolved_at: string | null
  resolved_by: string | null
}

export interface ResolveApprovalResponse {
  id: string
  status: string
  resolved_by: string
}

export interface AgentInfo {
  id: string
  role: string
  name: string
  llm_model: string
  tool_access: string[]
  is_active: boolean
  token_budget_per_task: number
}

export interface AgentEvent {
  event: string
  agent_id?: string
  task_id?: string
  status?: string
  error?: string
}
