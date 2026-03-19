import { ApprovalPanel } from '@/components/approvals/ApprovalPanel'
import { SubmitTaskPanel } from '@/components/tasks/SubmitTaskPanel'
import { TaskListPanel } from '@/components/tasks/TaskListPanel'

export function TasksPage() {
  return (
    <>
      <ApprovalPanel />
      <SubmitTaskPanel />
      <TaskListPanel />
    </>
  )
}
