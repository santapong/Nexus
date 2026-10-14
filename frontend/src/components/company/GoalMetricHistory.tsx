import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { MetricOutcomeLedger } from './MetricOutcomeLedger'

export function GoalMetricHistory({ company, goal }: { company: string; goal: string }) {
  const [open, setOpen] = useState(false)
  return <div className="space-y-3">
    <Button variant="outline" size="sm" onClick={() => setOpen(previous => !previous)}>
      {open ? 'Hide observations' : 'Inspect observations'}</Button>
    {open && <MetricOutcomeLedger company={company} goal={goal} />}
  </div>
}
