import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useNewCompanyReport } from '@/hooks/useCompanyReports'
import type { PlanView } from '@/types/company'

export function ReportSnapshotForm({ plan, paused }: { plan: PlanView; paused: boolean }) {
  const [author, setAuthor] = useState('')
  const [tasks, setTasks] = useState<string[]>([])
  const [start, setStart] = useState(''), [end, setEnd] = useState('')
  const action = useNewCompanyReport(plan)
  const edge = plan.declaration.verification.find(item => item.author_task_id === author)
  const locked = action.mutation.isPending || action.mutation.isSuccess || action.mutation.isError
  const title = (task: string) => plan.declaration.plan.items.find(item => item.task_id === task)?.title ?? task
  return <form className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4"
    onSubmit={event => { event.preventDefault(); action.save(author, tasks, start, end) }}>
    <div><h3 className="font-semibold text-white">Save an operating report</h3>
      <p className="text-xs text-gray-400 mt-2">Capture the selected work and its current facts for a dated report.</p></div>
    <fieldset disabled={locked || paused} className="space-y-4">
      <label className="block space-y-2 text-sm text-gray-300">Report author
        <select required value={author} onChange={event => { setAuthor(event.target.value); setTasks([]) }}
          className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2">
          <option value="">Choose report work from this plan</option>
          {plan.declaration.verification.map(item => <option key={item.verifier_task_id} value={item.author_task_id}>{title(item.author_task_id)}</option>)}
        </select></label>
      {edge && <p className="text-xs text-gray-400">Independent verifier: {title(edge.verifier_task_id)}</p>}
      <div className="grid sm:grid-cols-2 gap-4">
        <label className="block space-y-2 text-sm text-gray-300">Period start (your local timezone)
          <Input type="datetime-local" required value={start} onChange={event => setStart(event.target.value)} /></label>
        <label className="block space-y-2 text-sm text-gray-300">Period end (your local timezone)
          <Input type="datetime-local" required value={end} onChange={event => setEnd(event.target.value)} /></label>
      </div>
      <fieldset className="space-y-2"><legend className="text-sm text-gray-300 mb-2">Existing work to include</legend>
        {plan.work.filter(row => row.work.task_id !== author && row.work.task_id !== edge?.verifier_task_id).map(row =>
          <label key={row.work.task_id} className="flex gap-3 items-start text-sm text-gray-400">
            <input type="checkbox" checked={tasks.includes(row.work.task_id)} onChange={event => setTasks(current => event.target.checked
              ? [...current, row.work.task_id] : current.filter(id => id !== row.work.task_id))} />{title(row.work.task_id)}</label>)}
        <p className="text-xs text-gray-500">Costs cover the selected work’s lifetime. The period labels the report; it does not reset spending.</p>
      </fieldset>
      <Button type="submit">{action.mutation.isPending ? 'Saving…' : 'Save new snapshot'}</Button>
    </fieldset>
    {(action.error || action.mutation.isError) && <p role="alert" className="text-sm text-red-400">{action.error ?? action.mutation.error?.message}</p>}
    {action.mutation.isError && <p className="text-xs text-amber-500">The response did not confirm a snapshot. A report may have been saved; creating another makes a separate record.</p>}
    {action.mutation.data && <Link className="block text-sm text-indigo-400 underline" to={`/company/reports/${action.mutation.data.report_id}`}>Open saved report</Link>}
    {(action.mutation.isSuccess || action.mutation.isError) && <Button type="button" variant="outline"
      onClick={action.newSnapshot}>Start a separate snapshot</Button>}
  </form>
}
