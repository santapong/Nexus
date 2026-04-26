import { LiveStatusBoard } from '@/components/agents/LiveStatusBoard'
import { ThinkingStream } from '@/components/agents/ThinkingStream'
import { BudgetAlert } from '@/components/dashboard/BudgetAlert'
import { HealthPanel } from '@/components/dashboard/HealthPanel'

export function LiveOperationsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-white tracking-tight">Live operations</h2>
        <p className="text-sm text-gray-400 mt-1 max-w-2xl">
          Watch the company at work in real time — agent state, tool calls, and the inner
          monologue stream as tasks flow through CEO → specialists → Director → QA.
        </p>
      </div>

      <LiveStatusBoard />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <ThinkingStream
            title="What the agents are thinking"
            subtitle="Live feed of LLM calls, tool calls, memory operations, and meeting messages"
            maxHeight="32rem"
          />
        </div>
        <div className="space-y-4">
          <BudgetAlert />
          <HealthPanel />
        </div>
      </div>
    </div>
  )
}
