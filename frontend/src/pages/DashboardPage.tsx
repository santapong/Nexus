import { HealthPanel } from '@/components/dashboard/HealthPanel'
import { ApprovalPanel } from '@/components/approvals/ApprovalPanel'
import { SubmitTaskPanel } from '@/components/tasks/SubmitTaskPanel'
import { TaskListPanel } from '@/components/tasks/TaskListPanel'
import { AgentOrgChart } from '@/components/agents/AgentOrgChart'

export function DashboardPage() {
  return (
    <>
      <ApprovalPanel />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="md:col-span-1">
          <HealthPanel />
        </div>
        <div className="md:col-span-2">
          <SubmitTaskPanel />
        </div>
      </div>

      <TaskListPanel />
      <AgentOrgChart />
    </>
  )
}
