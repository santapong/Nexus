import { create } from 'zustand'

export type AgentLifecycleState =
  | 'idle'
  | 'thinking'
  | 'calling_tool'
  | 'waiting'
  | 'failed'

export interface AgentLiveStatus {
  agent_id: string
  state: AgentLifecycleState
  task_id?: string
  instruction_snippet?: string
  last_event_at: number
  last_heartbeat_at?: number
  recent_error?: string
}

export interface ThinkingEntry {
  id: string
  task_id?: string
  agent_id?: string
  kind:
    | 'task_started'
    | 'task_completed'
    | 'task_failed'
    | 'state_change'
    | 'llm_call'
    | 'tool_call'
    | 'tool_result'
    | 'memory_read'
    | 'memory_write'
    | 'meeting_message'
    | 'meeting_convergence'
    | 'system'
  text: string
  detail?: string
  timestamp: number
  tone: 'info' | 'success' | 'warn' | 'error' | 'thinking' | 'tool'
}

export interface RawAgentEvent {
  event?: string
  agent_id?: string
  task_id?: string
  status?: string
  error?: string
  from_state?: string
  to_state?: string
  instruction_snippet?: string
  event_type?: string
  detail?: Record<string, unknown>
  meeting_id?: string
  message_type?: string
  sender_role?: string
  sender_id?: string
  round_number?: number
  content?: string
  recommendation?: string
  is_converging?: boolean
  is_looping?: boolean
  is_stagnating?: boolean
}

interface AgentEventStore {
  agents: Record<string, AgentLiveStatus>
  thinking: ThinkingEntry[]
  connectionState: 'connecting' | 'open' | 'closed'
  pushEvent: (raw: RawAgentEvent) => void
  setConnectionState: (s: 'connecting' | 'open' | 'closed') => void
  clearThinking: () => void
}

const MAX_THINKING_ENTRIES = 250

let entryCounter = 0
function nextId(): string {
  entryCounter += 1
  return `evt-${Date.now()}-${entryCounter}`
}

function deriveStateFromEvent(raw: RawAgentEvent): AgentLifecycleState | null {
  if (raw.event === 'task_started') return 'thinking'
  if (raw.event === 'task_completed') return 'idle'
  if (raw.event === 'task_failed') return 'failed'
  if (raw.event === 'agent_state_change' && raw.to_state) {
    const s = raw.to_state.toLowerCase()
    if (s === 'idle' || s === 'thinking' || s === 'calling_tool' || s === 'waiting' || s === 'failed') {
      return s
    }
  }
  if (raw.event === 'agent_thinking_update') {
    const t = raw.event_type
    if (t === 'tool_call' || t === 'tool_result') return 'calling_tool'
    if (t === 'llm_call_started' || t === 'llm_partial') return 'thinking'
  }
  return null
}

function deriveEntry(raw: RawAgentEvent): ThinkingEntry | null {
  const ts = Date.now()
  const base = {
    id: nextId(),
    task_id: raw.task_id,
    agent_id: raw.agent_id,
    timestamp: ts,
  }

  switch (raw.event) {
    case 'task_started':
      return {
        ...base,
        kind: 'task_started',
        text: `Task started`,
        detail: raw.instruction_snippet,
        tone: 'info',
      }
    case 'task_completed':
      return {
        ...base,
        kind: 'task_completed',
        text: `Task completed`,
        detail: raw.status,
        tone: 'success',
      }
    case 'task_failed':
      return {
        ...base,
        kind: 'task_failed',
        text: `Task failed`,
        detail: raw.error,
        tone: 'error',
      }
    case 'agent_state_change':
      return {
        ...base,
        kind: 'state_change',
        text: `${raw.from_state ?? '?'} → ${raw.to_state ?? '?'}`,
        detail: raw.instruction_snippet,
        tone: 'info',
      }
    case 'agent_thinking_update': {
      const detail = raw.detail ?? {}
      switch (raw.event_type) {
        case 'llm_call_started':
          return {
            ...base,
            kind: 'llm_call',
            text: `LLM call started`,
            detail: typeof detail.model === 'string' ? `model=${detail.model}` : undefined,
            tone: 'thinking',
          }
        case 'llm_partial':
          return {
            ...base,
            kind: 'llm_call',
            text: 'Thinking…',
            detail: typeof detail.text === 'string' ? detail.text : undefined,
            tone: 'thinking',
          }
        case 'tool_call':
          return {
            ...base,
            kind: 'tool_call',
            text: `Tool call: ${typeof detail.name === 'string' ? detail.name : 'unknown'}`,
            detail: typeof detail.args === 'string' ? detail.args : JSON.stringify(detail.args ?? {}),
            tone: 'tool',
          }
        case 'tool_result':
          return {
            ...base,
            kind: 'tool_result',
            text: `Tool result: ${typeof detail.name === 'string' ? detail.name : 'unknown'}`,
            detail:
              typeof detail.success === 'boolean'
                ? detail.success
                  ? 'success'
                  : 'failed'
                : undefined,
            tone: detail.success === false ? 'warn' : 'success',
          }
        case 'memory_read':
          return {
            ...base,
            kind: 'memory_read',
            text: `Memory read`,
            detail: typeof detail.count === 'number' ? `${detail.count} episodes` : undefined,
            tone: 'info',
          }
        case 'memory_write':
          return {
            ...base,
            kind: 'memory_write',
            text: `Memory write`,
            detail: typeof detail.summary === 'string' ? detail.summary : undefined,
            tone: 'info',
          }
        default:
          return {
            ...base,
            kind: 'state_change',
            text: `Update: ${raw.event_type ?? 'unknown'}`,
            tone: 'info',
          }
      }
    }
    case 'meeting_message_published':
      return {
        ...base,
        kind: 'meeting_message',
        text: `${raw.sender_role ?? 'agent'} (round ${raw.round_number ?? '?'})`,
        detail: raw.content,
        tone: 'info',
      }
    case 'meeting_convergence_update':
      return {
        ...base,
        kind: 'meeting_convergence',
        text: `Meeting: ${raw.recommendation ?? 'analyzing'}`,
        detail: raw.is_looping
          ? 'looping'
          : raw.is_stagnating
            ? 'stagnating'
            : raw.is_converging
              ? 'converging'
              : undefined,
        tone: raw.is_looping ? 'warn' : 'info',
      }
    default:
      return null
  }
}

export const useAgentEventStore = create<AgentEventStore>((set) => ({
  agents: {},
  thinking: [],
  connectionState: 'connecting',
  setConnectionState: (s) => set({ connectionState: s }),
  clearThinking: () => set({ thinking: [] }),
  pushEvent: (raw) =>
    set((store) => {
      const next: Partial<AgentEventStore> = {}

      if (raw.agent_id) {
        const prior = store.agents[raw.agent_id]
        const derivedState = deriveStateFromEvent(raw)
        next.agents = {
          ...store.agents,
          [raw.agent_id]: {
            agent_id: raw.agent_id,
            state: derivedState ?? prior?.state ?? 'idle',
            task_id: raw.task_id ?? prior?.task_id,
            instruction_snippet:
              raw.instruction_snippet ?? prior?.instruction_snippet,
            last_event_at: Date.now(),
            last_heartbeat_at:
              raw.event === 'agent_heartbeat' ? Date.now() : prior?.last_heartbeat_at,
            recent_error: raw.event === 'task_failed' ? raw.error : prior?.recent_error,
          },
        }
      }

      const entry = deriveEntry(raw)
      if (entry) {
        const updated = [entry, ...store.thinking].slice(0, MAX_THINKING_ENTRIES)
        next.thinking = updated
      }

      return next
    }),
}))
