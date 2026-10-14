import { createBrowserRouter } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { CoPage } from '@/pages/CoPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { LiveOperationsPage } from '@/pages/LiveOperationsPage'
import { TasksPage } from '@/pages/TasksPage'
import { AgentsPage } from '@/pages/AgentsPage'
import { AnalyticsPage } from '@/pages/AnalyticsPage'
import { MarketplacePage } from '@/pages/MarketplacePage'
import { A2ATokensPage } from '@/pages/A2ATokensPage'
import { PromptsPage } from '@/pages/PromptsPage'
import { BillingPage } from '@/pages/BillingPage'
import { AuditPage } from '@/pages/AuditPage'
import { LoginPage } from '@/pages/LoginPage'
import { Navigate } from 'react-router-dom'
import { CompanyLayout } from '@/components/company/CompanyLayout'
import { CompanyTodayPage } from '@/pages/CompanyTodayPage'
import { CompanyOverviewPage } from '@/pages/CompanyOverviewPage'
import { CompanyPlanPage } from '@/pages/CompanyPlanPage'
import { CompanyWorkPage } from '@/pages/CompanyWorkPage'
import { CompanyReportPage } from '@/pages/CompanyReportPage'
import { CompanyApprovalsPage } from '@/pages/CompanyApprovalsPage'
import { CompanyActionReviewPage } from '@/pages/CompanyActionReviewPage'
import { CompanyLoginPage } from '@/pages/CompanyLoginPage'

export const router = createBrowserRouter([
  { path: '/company/login', element: <CompanyLoginPage /> },
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/company', element: <CompanyLayout />, children: [
      { index: true, element: <Navigate to="today" replace /> },
      { path: 'today', element: <CompanyTodayPage /> },
      { path: 'overview', element: <CompanyOverviewPage /> },
      { path: 'plans/:planId', element: <CompanyPlanPage /> },
      { path: 'work/:taskId', element: <CompanyWorkPage /> },
      { path: 'reports/:reportId', element: <CompanyReportPage /> },
      { path: 'approvals', element: <CompanyApprovalsPage /> },
      { path: 'actions/:actionId', element: <CompanyActionReviewPage /> },
    ],
  },
  {
    element: <AppLayout />,
    children: [
      { index: true, element: <CoPage /> },
      { path: 'dashboard', element: <DashboardPage /> },
      { path: 'live', element: <LiveOperationsPage /> },
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
