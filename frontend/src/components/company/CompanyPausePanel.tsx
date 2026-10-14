import { Button } from '@/components/ui/button'
import { useCompanyPause } from '@/hooks/useCompanyControls'

export function CompanyPausePanel({ companyId, paused }: { companyId: string; paused: boolean }) {
  const action = useCompanyPause(companyId)
  const requested = action.variables ?? !paused
  return <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-3">
    <h3 className="font-semibold text-white">Company controls</h3>
    <p className="text-sm text-gray-400">Pause stops new work. Issued results and spending remain in history.
      Resume preserves permanent work cancellations and the current approvals and limits.</p>
    <Button variant="outline" disabled={action.isPending}
      onClick={() => action.mutate(action.isError ? requested : !paused)}>
      {action.isPending ? 'Saving company control…' : action.isError
        ? `Retry ${requested ? 'pause' : 'resume'}` : paused ? 'Resume company' : 'Pause company'}
    </Button>
    {action.isError && <p role="alert" className="text-sm text-red-400">{action.error.message}</p>}
    {action.isSuccess && <p role="status" className="text-sm text-emerald-500">
      Company {action.data.paused ? 'paused' : 'resumed'}.</p>}
  </section>
}
