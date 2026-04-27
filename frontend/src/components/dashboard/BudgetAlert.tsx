import { useMemo } from 'react'
import { AlertTriangle, CircleDollarSign, Sparkles } from 'lucide-react'
import { useBillingSummary } from '@/hooks/useBilling'
import { useWorkspaces } from '@/hooks/useWorkspaces'
import { cn } from '@/lib/utils'

interface BudgetAlertProps {
  /** Optional embedded variant for top bars. */
  compact?: boolean
  className?: string
}

const FREE_TIER_FALLBACK_LIMIT_USD = 5

export function BudgetAlert({ compact, className }: BudgetAlertProps) {
  const { data: summary } = useBillingSummary('1d')
  const { data: workspaces = [] } = useWorkspaces()

  const dailyLimit = useMemo(() => {
    const wsLimit = workspaces[0]?.daily_spend_limit_usd
    if (typeof wsLimit === 'number' && wsLimit > 0) return wsLimit
    return FREE_TIER_FALLBACK_LIMIT_USD
  }, [workspaces])

  const todaySpend = summary?.total_cost_usd ?? 0
  const ratio = dailyLimit > 0 ? Math.min(1, todaySpend / dailyLimit) : 0
  const percent = Math.round(ratio * 100)

  const tone = ratio >= 0.9 ? 'danger' : ratio >= 0.6 ? 'warn' : 'ok'

  // When using free models the spend stays at $0 — show a friendly free-tier badge instead.
  const onFreeModels = todaySpend === 0

  if (compact) {
    return (
      <div
        className={cn(
          'inline-flex items-center gap-2 px-2.5 py-1 rounded-full border text-[11px]',
          tone === 'danger' && 'border-red-700 bg-red-900/30 text-red-200',
          tone === 'warn' && 'border-amber-700 bg-amber-900/30 text-amber-200',
          tone === 'ok' && 'border-gray-700 bg-gray-900 text-gray-300',
          className,
        )}
        role="status"
        aria-label={`Today's spend ${todaySpend.toFixed(2)} of ${dailyLimit.toFixed(2)} dollar limit`}
      >
        {tone === 'danger' ? (
          <AlertTriangle size={12} aria-hidden="true" />
        ) : onFreeModels ? (
          <Sparkles size={12} aria-hidden="true" />
        ) : (
          <CircleDollarSign size={12} aria-hidden="true" />
        )}
        {onFreeModels ? (
          <span>Free tier · $0.00 today</span>
        ) : (
          <span>
            ${todaySpend.toFixed(2)} / ${dailyLimit.toFixed(2)} ({percent}%)
          </span>
        )}
      </div>
    )
  }

  return (
    <section
      className={cn(
        'rounded-lg border p-4 space-y-3',
        tone === 'danger' && 'border-red-800 bg-red-950/30',
        tone === 'warn' && 'border-amber-800 bg-amber-950/30',
        tone === 'ok' && 'border-gray-800 bg-gray-900',
        className,
      )}
      aria-label="Token budget"
    >
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {tone === 'danger' ? (
            <AlertTriangle size={16} className="text-red-400" aria-hidden="true" />
          ) : (
            <CircleDollarSign size={16} className="text-gray-400" aria-hidden="true" />
          )}
          <h3 className="text-sm font-semibold text-white">Daily spend</h3>
        </div>
        <span className="text-xs text-gray-400">
          ${todaySpend.toFixed(2)} of ${dailyLimit.toFixed(2)}
        </span>
      </header>
      <div className="h-2 w-full rounded-full bg-gray-800 overflow-hidden">
        <div
          className={cn(
            'h-full transition-all',
            tone === 'danger' && 'bg-red-500',
            tone === 'warn' && 'bg-amber-500',
            tone === 'ok' && 'bg-emerald-500',
          )}
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="text-[11px] text-gray-500">
        {onFreeModels
          ? 'Running on free-tier models — no billed spend recorded today.'
          : tone === 'danger'
            ? 'Approaching the daily cap. New tasks may be paused for human approval.'
            : tone === 'warn'
              ? 'More than 60% of today’s budget used.'
              : 'Comfortably within today’s budget.'}
      </p>
    </section>
  )
}
