import { useLocation } from 'react-router-dom'
import { Bell } from 'lucide-react'
import { useApprovals } from '@/hooks/useApprovals'

const pageTitles: Record<string, string> = {
  '/': 'Dashboard',
  '/tasks': 'Tasks',
  '/agents': 'Agents',
  '/analytics': 'Analytics',
  '/marketplace': 'Marketplace',
  '/settings/a2a-tokens': 'A2A Tokens',
  '/settings/prompts': 'Prompts',
  '/settings/billing': 'Billing',
  '/settings/audit': 'Audit Log',
}

export function AppHeader() {
  const location = useLocation()
  const { data: approvals = [] } = useApprovals()
  const pendingCount = approvals.filter((a) => a.status === 'pending').length

  const title = pageTitles[location.pathname] ?? 'NEXUS'

  const breadcrumb = location.pathname
    .split('/')
    .filter(Boolean)
    .map((segment) =>
      segment
        .split('-')
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(' '),
    )

  return (
    <header className="flex items-center justify-between border-b border-gray-800 bg-gray-950/80 backdrop-blur-sm px-6 py-4 sticky top-0 z-10">
      <div>
        <div className="flex items-center gap-2 text-xs text-gray-500 mb-1">
          <span>NEXUS</span>
          {breadcrumb.map((crumb, i) => (
            <span key={i} className="flex items-center gap-2">
              <span>/</span>
              <span className={i === breadcrumb.length - 1 ? 'text-gray-300' : ''}>{crumb}</span>
            </span>
          ))}
        </div>
        <h1 className="text-xl font-semibold text-white">{title}</h1>
      </div>

      <div className="flex items-center gap-3">
        {pendingCount > 0 && (
          <div className="relative">
            <Bell size={20} className="text-gray-400" />
            <span className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-red-600 text-[9px] text-white font-bold">
              {pendingCount}
            </span>
          </div>
        )}
      </div>
    </header>
  )
}
