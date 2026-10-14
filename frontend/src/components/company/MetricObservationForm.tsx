import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { useMetricObservation } from '@/hooks/useCompanyMetrics'
import type { GoalView, PlanView } from '@/types/company'

export function MetricObservationForm({ plan, goal }: { plan: PlanView; goal: GoalView }) {
  const [metric, setMetric] = useState(goal.metrics[0]?.metric_id ?? '')
  const [tasks, setTasks] = useState<string[]>(() => Array.from(new Set(
    plan.declaration.verification.map(item => item.author_task_id))))
  const { attempt, mutation, observe, newObservation } = useMetricObservation(plan)
  return <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
    <h3 className="font-semibold text-white">Record measured outcome</h3>
    <p className="text-sm text-gray-400">Nexus checks independent acceptance for the selected work.
      Recording a measurement does not complete the goal or start new work.</p>
    <label className="block text-sm text-gray-300">Declared goal metric
      <select value={metric} disabled={attempt !== null} onChange={event => setMetric(event.target.value)}
        className="mt-2 w-full rounded border border-gray-700 bg-gray-950 p-2">
        {goal.metrics.map(item => <option key={item.metric_id} value={item.metric_id}>
          {item.metric_id} · {item.comparator} {item.target} {item.unit}</option>)}
      </select>
    </label>
    <fieldset className="space-y-2" disabled={attempt !== null}>
      <legend className="text-sm text-gray-300 mb-2">Select actual registered work</legend>
      {plan.declaration.children.map(child => <label key={child.binding.task_id} className="flex gap-3 text-sm text-gray-400">
        <input type="checkbox" checked={tasks.includes(child.binding.task_id)} className="accent-indigo-500"
          onChange={event => setTasks(previous => event.target.checked
            ? [...previous, child.binding.task_id] : previous.filter(id => id !== child.binding.task_id))} />
        <span>{plan.declaration.plan.items.find(item => item.task_id === child.binding.task_id)?.title ?? 'Registered work'}
          <span className="block text-xs text-gray-500">{plan.declaration.verification.some(item => item.author_task_id === child.binding.task_id)
            ? 'Author work' : plan.declaration.verification.some(item => item.verifier_task_id === child.binding.task_id)
              ? 'Independent verifier' : 'Registered work'} · {child.binding.task_id.slice(0, 8)}</span></span>
      </label>)}
    </fieldset>
    {mutation.isSuccess ? <div className="space-y-3">
      <p role="status" className="text-sm text-emerald-500">Observation recorded. Review its fresh reading below.</p>
      <Button variant="outline" onClick={newObservation}>Prepare another observation</Button>
    </div> : <Button disabled={!metric || tasks.length === 0 || tasks.length > 100 || mutation.isPending}
      onClick={() => observe(metric, tasks)}>{mutation.isPending ? 'Checking native evidence…'
        : attempt ? 'Retry exact observation' : 'Record observation'}</Button>}
    {mutation.isError && <p role="alert" className="text-sm text-red-400">{mutation.error.message}
      {' '}Retry preserves this exact selection and request identity. Refresh to inspect current records.</p>}
  </section>
}
