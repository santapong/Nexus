import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { AgentOrgChart } from '@/components/agents/AgentOrgChart'
import { AgentStatusPanel } from '@/components/agents/AgentStatusPanel'
import { AgentBuilderPanel } from '@/components/agent-builder/AgentBuilderPanel'

export function AgentsPage() {
  return (
    <Tabs defaultValue="org-chart">
      <TabsList>
        <TabsTrigger value="org-chart">Organization</TabsTrigger>
        <TabsTrigger value="status">Status</TabsTrigger>
        <TabsTrigger value="builder">Agent Builder</TabsTrigger>
      </TabsList>

      <TabsContent value="org-chart">
        <AgentOrgChart />
      </TabsContent>

      <TabsContent value="status">
        <AgentStatusPanel />
      </TabsContent>

      <TabsContent value="builder">
        <AgentBuilderPanel />
      </TabsContent>
    </Tabs>
  )
}
