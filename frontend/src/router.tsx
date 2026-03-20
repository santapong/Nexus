import { createBrowserRouter } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { DashboardPage } from '@/pages/DashboardPage'
import { TasksPage } from '@/pages/TasksPage'
import { AgentsPage } from '@/pages/AgentsPage'
import { AnalyticsPage } from '@/pages/AnalyticsPage'
import { MarketplacePage } from '@/pages/MarketplacePage'
import { A2ATokensPage } from '@/pages/A2ATokensPage'
import { PromptsPage } from '@/pages/PromptsPage'
import { BillingPage } from '@/pages/BillingPage'
import { AuditPage } from '@/pages/AuditPage'
import { LoginPage } from '@/pages/LoginPage'

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    element: <AppLayout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'tasks', element: <TasksPage /> },
      { path: 'agents', element: <AgentsPage /> },
      { path: 'analytics', element: <AnalyticsPage /> },
      { path: 'marketplace', element: <MarketplacePage /> },
      { path: 'settings/a2a-tokens', element: <A2ATokensPage /> },
      { path: 'settings/prompts', element: <PromptsPage /> },
      { path: 'settings/billing', element: <BillingPage /> },
      { path: 'settings/audit', element: <AuditPage /> },
    ],
  },
])
