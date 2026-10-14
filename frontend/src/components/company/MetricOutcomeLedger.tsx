import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { useCompanyMetrics } from '@/hooks/useCompanyMetrics'
import { CompanyQueryState } from './CompanyStatus'
import { MetricReading } from './MetricReading'

export function MetricOutcomeLedger({ company, goal }: { company: string; goal: string }) {
  const [after, setAfter] = useState<string | null>(null)
  const query = useCompanyMetrics(company, goal, after)
  const data = query.data
  return <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
    <div className="flex flex-wrap justify-between gap-3"><h3 className="font-semibold text-white">Measured outcomes</h3>
      <Button variant="outline" size="sm" disabled={query.isFetching} onClick={() => { void query.refetch() }}>Refresh readings</Button></div>
    <p className="text-xs text-gray-500">Fresh readings use current permissions and native proof.
      A target comparison does not mark the goal completed.</p>
    <CompanyQueryState pending={query.isPending} error={query.error} />
    {data && !query.isError && data.observations.map(reading =>
      <MetricReading key={reading.observation_id + ':' + reading.checked_at} reading={reading} />)}
    {data && !query.isError && data.observations.length === 0 && <p className="text-sm text-gray-400">No recorded observation in this page.</p>}
    <div className="flex flex-wrap gap-3">
      {after && <Button variant="outline" size="sm" onClick={() => setAfter(null)}>Newest observations</Button>}
      {data?.next_after_id && <Button variant="outline" size="sm" onClick={() => setAfter(data.next_after_id)}>Older observations</Button>}
    </div>
  </section>
}
