import { Button } from '@/components/ui/button'
import { instant, StateLabel } from './CompanyStatus'
import { useRecordedMetric } from '@/hooks/useCompanyMetrics'
import type { MetricCurrentObservation } from '@/types/company'

export function MetricReading({ reading }: { reading: MetricCurrentObservation }) {
  const recorded = useRecordedMetric(reading.company_id, reading.observation_id)
  const comparison = reading.snapshot.comparison
  const value = comparison.value
  return <article className="border-t border-gray-800 pt-4 space-y-3">
    <div className="flex flex-wrap justify-between gap-2">
      <p className="font-medium text-gray-200">{reading.snapshot.request.metric_id}</p>
      <StateLabel warn={reading.comparison_result !== 'satisfied'}>
        {reading.comparison_result === 'satisfied' ? 'Target met for selected work'
          : reading.comparison_result === 'unsatisfied' ? 'Target not met for selected work' : 'Current result unknown'}
      </StateLabel>
    </div>
    <p className="text-sm text-gray-300">{value.kind === 'known' ? `${value.value} ${value.unit}`
      : `Unknown · ${value.reason.replace(/_/g, ' ')}`} · Target {comparison.comparator} {comparison.target}</p>
    <p className="text-xs text-gray-400">{comparison.baseline.kind === 'known'
      ? `Recorded baseline ${comparison.baseline.value}${reading.baseline_change === null ? '' : ` · Change ${reading.baseline_change}`}`
      : `Baseline unknown · ${comparison.baseline.reason}`}</p>
    <p className="text-xs text-gray-500">Recorded {instant(reading.recorded_at)} · Checked {instant(reading.checked_at)}</p>
    <p className="text-xs text-gray-500">{reading.snapshot.work.length} selected work items · {value.kind === 'known'
      ? `${reading.snapshot.work.filter(item => item.status === 'accepted_report').length} reports currently pass independent checks`
      : 'Current report acceptance cannot be confirmed for this selection'}</p>
    {reading.snapshot.sources.slice(0, 8).map(source => <p key={source.source.source_revision_id}
      className="text-xs text-gray-500">Source time: {source.source_event.precision === 'unknown' ? 'unknown'
        : `${source.source_event.value} (${source.source_event.precision})`} · Ingested {instant(source.ingested_at)}</p>)}
    {reading.snapshot.sources.length > 8 && <p className="text-xs text-gray-500">
      Showing 8 of {reading.snapshot.sources.length} current supporting sources.</p>}
    <Button variant="outline" size="sm" disabled={recorded.isPending} onClick={() => recorded.mutate()}>
      {recorded.isPending ? 'Checking history permissions…' : 'Inspect dated observation'}</Button>
    {recorded.isError && <p role="alert" className="text-sm text-red-400">{recorded.error.message}</p>}
    {recorded.isSuccess && <details className="text-xs text-gray-400">
      <summary className="cursor-pointer">Dated observation · {instant(recorded.data.observed_at)}</summary>
      <p className="my-2">This preserved record describes the original observation time. Current reading is shown above.</p>
      <pre className="whitespace-pre-wrap break-all">{JSON.stringify(recorded.data, null, 2)}</pre>
    </details>}
  </article>
}
