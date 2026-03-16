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

// ─── Analytics Types ────────────────────────────────────────────────────────

export interface AgentPerformance {
  role: string
  name: string
  total_tasks: number
  completed: number
  failed: number
  success_rate: number
  avg_tokens: number
  avg_duration_seconds: number | null
  total_cost_usd: number
}

export interface PerformanceData {
  period: string
  agents: AgentPerformance[]
  total_tasks: number
  overall_success_rate: number
  total_cost_usd: number
}

export interface CostByModel {
  model_name: string
  total_calls: number
  total_input_tokens: number
  total_output_tokens: number
  total_cost_usd: number
}

export interface CostByRole {
  role: string
  total_calls: number
  total_cost_usd: number
}

export interface CostBreakdown {
  period: string
  by_model: CostByModel[]
  by_role: CostByRole[]
  total_cost_usd: number
  daily_average_usd: number
}

export interface ReplayEpisode {
  agent_id: string
  summary: string
  full_context: Record<string, unknown>
  outcome: string
  tools_used: string[] | null
  tokens_used: number | null
  duration_seconds: number | null
  importance_score: number
  created_at: string
}

export interface ReplayLLMCall {
  agent_id: string
  model_name: string
  input_tokens: number
  output_tokens: number
  cost_usd: number
  created_at: string
}

export interface TaskReplay {
  task: {
    id: string
    instruction: string
    status: string
    tokens_used: number
    created_at: string
    completed_at: string | null
  }
  episodes: ReplayEpisode[]
  llm_calls: ReplayLLMCall[]
  subtask_episodes: Array<ReplayEpisode & { subtask_id: string }>
  subtask_llm_calls: Array<ReplayLLMCall & { subtask_id: string }>
  total_episodes: number
  total_llm_calls: number
}

export interface DeadLetterStats {
  topic: string
  count: number
  oldest: string | null
  newest: string | null
}

export interface DeadLetterData {
  total_dead_letters: number
  unresolved: number
  by_topic: DeadLetterStats[]
}

// --- Audit Types ---

export interface AuditEvent {
  id: string
  task_id: string
  trace_id: string
  agent_id: string
  event_type: string
  event_data: Record<string, unknown>
  created_at: string
}

export interface AuditListData {
  events: AuditEvent[]
  total: number
}

export interface AuditTimelineEntry {
  id: string
  event_type: string
  agent_id: string
  event_data: Record<string, unknown>
  created_at: string
}
