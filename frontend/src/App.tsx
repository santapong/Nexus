import { AgentStatusPanel } from './components/agents/AgentStatusPanel'
import { ApprovalPanel } from './components/approvals/ApprovalPanel'
import { HealthPanel } from './components/dashboard/HealthPanel'
import { Layout } from './components/dashboard/Layout'
import { SubmitTaskPanel } from './components/tasks/SubmitTaskPanel'
import { TaskListPanel } from './components/tasks/TaskListPanel'
import { AgentWebSocketProvider } from './ws/AgentWebSocketProvider'

function App() {
  return (
    <AgentWebSocketProvider>
      <Layout>
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
        <AgentStatusPanel />
      </Layout>
    </AgentWebSocketProvider>
  )
}

export default App
