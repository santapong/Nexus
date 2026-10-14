import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { useCompanyControls, useWorkCancellation } from '@/hooks/useCompanyControls'
import type { WorkCancellationIntent, WorkView } from '@/types/company'

export function WorkCancellationPanel({ work }: { work: WorkView }) {
  const controls = useCompanyControls(work.company_id)
  const action = useWorkCancellation(work.company_id)
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [attempt, setAttempt] = useState<WorkCancellationIntent | null>(null)
  if (work.cancellation || action.isSuccess) return null
  if (controls.isPending) return <p role="status" className="text-sm text-gray-400">Checking owner controls…</p>
  if (controls.isError || !controls.data) return <p role="status" className="text-sm text-gray-400">
    Work cancellation is unavailable. {controls.error?.message}</p>
  const submit = () => {
    const body: WorkCancellationIntent = attempt ?? {
      intent: 'cancel_work_permanently', operation_id: crypto.randomUUID(), audit_trace_id: crypto.randomUUID(),
      command: { schema_version: 'nexus.company.management.v1', company_id: work.company_id,
        target: work.work, reason: reason.trim() },
    }
    setAttempt(body)
    action.mutate(body)
  }
  return <section className="rounded-lg border border-red-800/50 bg-gray-900 p-5 space-y-4">
    <h3 className="font-semibold text-white">Permanently cancel work</h3>
    <p className="text-sm text-gray-400">Stops this exact work and its registered descendants.
      Resuming the company cannot undo this cancellation. Issued results and spending remain recorded.</p>
    <label className="block text-sm text-gray-300">Cancellation reason
      <textarea value={reason} maxLength={500} disabled={attempt !== null}
        onChange={event => setReason(event.target.value)}
        className="mt-2 block w-full rounded border border-gray-700 bg-gray-950 p-3 disabled:opacity-60" />
    </label>
    <label className="flex gap-3 text-sm text-gray-300">
      <input type="checkbox" checked={confirmed} disabled={attempt !== null}
        onChange={event => setConfirmed(event.target.checked)} className="accent-red-500" />
      I intend to cancel this work permanently.
    </label>
    <Button variant="destructive" disabled={!confirmed || !reason.trim() || action.isPending} onClick={submit}>
      {action.isPending ? 'Recording cancellation…' : attempt ? 'Retry exact cancellation' : 'Cancel work permanently'}
    </Button>
    {action.isError && <p role="alert" className="text-sm text-red-400">{action.error.message}
      {' '}Retry keeps the same reason and request identity. Refresh the work to check its recorded state.</p>}
  </section>
}
