import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { AnalyticsDashboard } from '@/components/analytics/AnalyticsDashboard'
import { EvalScoreDashboard } from '@/components/eval/EvalScoreDashboard'

export function AnalyticsPage() {
  return (
    <Tabs defaultValue="performance">
      <TabsList>
        <TabsTrigger value="performance">Performance & Costs</TabsTrigger>
        <TabsTrigger value="eval">Eval Scores</TabsTrigger>
      </TabsList>

      <TabsContent value="performance">
        <AnalyticsDashboard />
      </TabsContent>

      <TabsContent value="eval">
        <EvalScoreDashboard />
      </TabsContent>
    </Tabs>
  )
}
