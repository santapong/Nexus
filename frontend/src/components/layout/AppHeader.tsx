import { useLocation, Link } from 'react-router-dom'
import { Bell } from 'lucide-react'
import { useApprovals } from '@/hooks/useApprovals'
import { useAgentEventStore } from '@/ws/agentEventStore'
import { BudgetAlert } from '@/components/dashboard/BudgetAlert'
import { cn } from '@/lib/utils'

const pageTitles: Record<string, string> = {
  '/': 'Dashboard',
  '/live': 'Live Operations',
  '/tasks': 'Tasks',
  '/agents': 'Agents',
  '/analytics': 'Analytics',
  '/marketplace': 'Marketplace',
  '/settings/a2a-tokens': 'A2A Tokens',
  '/settings/prompts': 'Prompts',
  '/settings/billing': 'Billing',
  '/settings/audit': 'Audit Log',
}

const segmentToPath: Record<string, string> = {
  Live: '/live',
  Tasks: '/tasks',
  Agents: '/agents',
  Analytics: '/analytics',
  Marketplace: '/marketplace',
  Settings: '/settings/a2a-tokens',
}

function prettify(segment: string): string {
  return segment
    .split('-')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

export function AppHeader() {
  const location = useLocation()
  const { data: approvals = [] } = useApprovals()
  const pendingCount = approvals.filter((a) => a.status === 'pending').length
  const connectionState = useAgentEventStore((s) => s.connectionState)

  const title = pageTitles[location.pathname] ?? 'NEXUS'

  const segments = location.pathname.split('/').filter(Boolean).map(prettify)

  return (
    <header className="flex items-center justify-between gap-4 border-b border-gray-800 bg-gray-950/80 backdrop-blur-sm px-6 py-4 sticky top-0 z-10">
      <div className="min-w-0">
        <nav className="flex items-center gap-2 text-xs text-gray-500 mb-1" aria-label="Breadcrumb">
          <Link to="/" className="hover:text-gray-300 transition-colors">
            NEXUS
          </Link>
          {segments.map((crumb, i) => {
            const path = segmentToPath[crumb]
            const isLast = i === segments.length - 1
            return (
              <span key={i} className="flex items-center gap-2">
                <span aria-hidden="true">/</span>
                {path && !isLast ? (
                  <Link to={path} className="hover:text-gray-300 transition-colors">
                    {crumb}
                  </Link>
                ) : (
                  <span className={isLast ? 'text-gray-300' : ''}>{crumb}</span>
                )}
              </span>
            )
          })}
        </nav>
        <h1 className="text-xl font-semibold text-white truncate">{title}</h1>
      </div>

      <div className="flex items-center gap-3 shrink-0">
        <BudgetAlert compact />
        <span
          className={cn(
            'inline-flex items-center gap-1.5 text-[11px] px-2 py-1 rounded-full border',
            connectionState === 'open'
              ? 'border-emerald-700 text-emerald-300 bg-emerald-900/20'
              : connectionState === 'connecting'
                ? 'border-amber-700 text-amber-300 bg-amber-900/20'
                : 'border-red-700 text-red-300 bg-red-900/20',
          )}
          role="status"
          aria-label={`Realtime connection ${connectionState}`}
        >
          <span
            className={cn(
              'h-1.5 w-1.5 rounded-full',
              connectionState === 'open'
                ? 'bg-emerald-400 animate-pulse'
                : connectionState === 'connecting'
                  ? 'bg-amber-400 animate-pulse'
                  : 'bg-red-400',
            )}
            aria-hidden="true"
          />
          {connectionState === 'open'
            ? 'Live'
            : connectionState === 'connecting'
              ? 'Connecting'
              : 'Offline'}
        </span>
        {pendingCount > 0 && (
          <Link
            to="/tasks"
            className="relative p-1.5 rounded-md text-gray-400 hover:text-gray-100 hover:bg-gray-800 transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500"
            aria-label={`${pendingCount} pending approval${pendingCount === 1 ? '' : 's'}`}
          >
            <Bell size={20} aria-hidden="true" />
            <span className="absolute -top-0.5 -right-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-red-600 text-[9px] text-white font-bold">
              {pendingCount}
            </span>
          </Link>
        )}
      </div>
    </header>
  )
}
