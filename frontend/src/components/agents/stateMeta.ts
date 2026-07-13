import {
  AlertTriangle,
  Brain,
  Clock,
  Pause,
  Wrench,
} from 'lucide-react'
import type { AgentLifecycleState } from '@/ws/agentEventStore'

/**
 * Shared visual metadata for agent lifecycle states.
 * Used by LiveStatusBoard tiles and the Co canvas nodes so live status
 * renders identically everywhere.
 */
export const STATE_META: Record<
  AgentLifecycleState,
  { label: string; ring: string; pulse: string; dot: string; icon: typeof Brain }
> = {
  idle: {
    label: 'Idle',
    ring: 'ring-gray-700',
    pulse: '',
    dot: 'bg-gray-500',
    icon: Pause,
  },
  thinking: {
    label: 'Thinking',
    ring: 'ring-blue-500/40',
    pulse: 'animate-pulse',
    dot: 'bg-blue-400',
    icon: Brain,
  },
  calling_tool: {
    label: 'Using tool',
    ring: 'ring-amber-500/40',
    pulse: 'animate-pulse',
    dot: 'bg-amber-400',
    icon: Wrench,
  },
  waiting: {
    label: 'Waiting',
    ring: 'ring-violet-500/40',
    pulse: '',
    dot: 'bg-violet-400',
    icon: Clock,
  },
  failed: {
    label: 'Failed',
    ring: 'ring-red-500/40',
    pulse: '',
    dot: 'bg-red-500',
    icon: AlertTriangle,
  },
}

/** Role → emoji/color/label map (shared by the org chart and Co canvas). */
export const ROLE_CONFIG: Record<string, { emoji: string; color: string; label: string }> = {
  ceo: { emoji: '🤝', color: 'border-amber-500', label: 'Co — Chief of Staff' },
  director: { emoji: '🎬', color: 'border-orange-500', label: 'Director' },
  engineer: { emoji: '💻', color: 'border-blue-500', label: 'Engineer' },
  analyst: { emoji: '🔍', color: 'border-purple-500', label: 'Analyst' },
  writer: { emoji: '✍️', color: 'border-green-500', label: 'Writer' },
  qa: { emoji: '🛡️', color: 'border-red-500', label: 'Quality Assurance' },
  prompt_creator: { emoji: '🧪', color: 'border-cyan-500', label: 'Prompt Creator' },
}

export function relativeSecondsAgo(ts?: number, now?: number): string | null {
  if (!ts) return null
  const seconds = Math.max(0, Math.floor(((now ?? Date.now()) - ts) / 1000))
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  return `${Math.floor(seconds / 3600)}h ago`
}
