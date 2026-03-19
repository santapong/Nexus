import { useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  ListTodo,
  Users,
  BarChart3,
  Store,
  Settings,
  Key,
  FileText,
  CreditCard,
  ScrollText,
  ChevronDown,
  ChevronRight,
  Sun,
  Moon,
  Menu,
  X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useApprovals } from '@/hooks/useApprovals'

interface SidebarProps {
  dark: boolean
  onToggleTheme: () => void
}

interface NavItem {
  label: string
  path: string
  icon: React.ReactNode
  children?: NavItem[]
}

const navItems: NavItem[] = [
  { label: 'Dashboard', path: '/', icon: <LayoutDashboard size={18} /> },
  { label: 'Tasks', path: '/tasks', icon: <ListTodo size={18} /> },
  { label: 'Agents', path: '/agents', icon: <Users size={18} /> },
  { label: 'Analytics', path: '/analytics', icon: <BarChart3 size={18} /> },
  { label: 'Marketplace', path: '/marketplace', icon: <Store size={18} /> },
  {
    label: 'Settings',
    path: '/settings',
    icon: <Settings size={18} />,
    children: [
      { label: 'A2A Tokens', path: '/settings/a2a-tokens', icon: <Key size={16} /> },
      { label: 'Prompts', path: '/settings/prompts', icon: <FileText size={16} /> },
      { label: 'Billing', path: '/settings/billing', icon: <CreditCard size={16} /> },
      { label: 'Audit Log', path: '/settings/audit', icon: <ScrollText size={16} /> },
    ],
  },
]

export function Sidebar({ dark, onToggleTheme }: SidebarProps) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const { data: approvals = [] } = useApprovals()
  const pendingCount = approvals.filter((a) => a.status === 'pending').length

  const isSettingsActive = location.pathname.startsWith('/settings')

  return (
    <>
      {/* Mobile toggle */}
      <button
        className="fixed top-4 left-4 z-50 md:hidden p-2 rounded-md bg-gray-800 text-gray-100 border border-gray-700"
        onClick={() => setMobileOpen(!mobileOpen)}
      >
        {mobileOpen ? <X size={20} /> : <Menu size={20} />}
      </button>

      {/* Overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-gray-800 bg-gray-950 transition-transform md:translate-x-0',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        {/* Logo */}
        <div className="flex items-center gap-2 px-5 py-5 border-b border-gray-800">
          <div className="h-8 w-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white font-bold text-sm">
            N
          </div>
          <div>
            <h1 className="text-lg font-bold text-white tracking-tight">NEXUS</h1>
            <p className="text-[10px] text-gray-500 leading-tight">Agentic AI Company</p>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-1">
          {navItems.map((item) => {
            if (item.children) {
              return (
                <div key={item.label}>
                  <button
                    onClick={() => setSettingsOpen(!settingsOpen)}
                    className={cn(
                      'flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                      isSettingsActive
                        ? 'text-white bg-gray-800/50'
                        : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50',
                    )}
                  >
                    {item.icon}
                    <span className="flex-1 text-left">{item.label}</span>
                    {settingsOpen || isSettingsActive ? (
                      <ChevronDown size={14} />
                    ) : (
                      <ChevronRight size={14} />
                    )}
                  </button>
                  {(settingsOpen || isSettingsActive) && (
                    <div className="ml-4 mt-1 space-y-1">
                      {item.children.map((child) => (
                        <NavLink
                          key={child.path}
                          to={child.path}
                          onClick={() => setMobileOpen(false)}
                          className={({ isActive }) =>
                            cn(
                              'flex items-center gap-3 rounded-md px-3 py-1.5 text-sm transition-colors',
                              isActive
                                ? 'text-white bg-gray-800'
                                : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50',
                            )
                          }
                        >
                          {child.icon}
                          {child.label}
                        </NavLink>
                      ))}
                    </div>
                  )}
                </div>
              )
            }

            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === '/'}
                onClick={() => setMobileOpen(false)}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors relative',
                    isActive
                      ? 'text-white bg-indigo-600/20 border border-indigo-600/30'
                      : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50',
                  )
                }
              >
                {item.icon}
                {item.label}
                {item.label === 'Tasks' && pendingCount > 0 && (
                  <span className="ml-auto flex h-5 w-5 items-center justify-center rounded-full bg-red-600 text-[10px] text-white font-bold">
                    {pendingCount}
                  </span>
                )}
              </NavLink>
            )
          })}
        </nav>

        {/* Footer */}
        <div className="border-t border-gray-800 px-3 py-3">
          <button
            onClick={onToggleTheme}
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-gray-400 hover:text-gray-200 hover:bg-gray-800/50 transition-colors"
          >
            {dark ? <Sun size={16} /> : <Moon size={16} />}
            {dark ? 'Light Mode' : 'Dark Mode'}
          </button>
        </div>
      </aside>
    </>
  )
}
