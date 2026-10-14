import { Link, useOutletContext, useParams } from 'react-router-dom'
import { useSavedCompanyReport } from '@/hooks/useCompanyReports'
import type { CompanyIdentity } from '@/types/company'
import { CompanyQueryState, instant, money, StateLabel } from '@/components/company/CompanyStatus'
import { ReportPreparationPanel } from '@/components/company/ReportPreparationPanel'

export function CompanyReportPage() {
  const identity = useOutletContext<CompanyIdentity>()
  const { reportId } = useParams()
  const query = useSavedCompanyReport(identity.company_id, reportId)
  if (query.isPending || query.isError) return <CompanyQueryState pending={query.isPending}
    error={query.error} refresh={() => { void query.refetch() }} />
  const report = query.data, projection = report.projection
  return <div className="space-y-5">
    <div><h2 className="text-2xl font-semibold text-white">Saved operating report</h2>
      <p className="text-xs text-gray-400 mt-2">Observed {instant(report.observed_at)} · dated history</p>
      <p className="font-mono break-all text-xs text-gray-500 mt-2">{report.report_id}</p></div>
    <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-3">
      <p className="text-sm text-gray-300">Period: {instant(report.period_start)} – {instant(report.period_end)}</p>
      <div className="grid sm:grid-cols-3 gap-4 text-sm">
        <p className="text-gray-400">Actual total<br /><strong className="text-white">{money(projection.actual_total_usd)}</strong></p>
        <p className="text-gray-400">Held allowance<br /><strong className="text-white">{money(projection.snapshot.ledger.held_usd)}</strong></p>
        <p className="text-gray-400">Unknown charges<br /><strong className="text-white">{projection.unknown_charge_ids.length}</strong></p>
      </div>
      <p className="text-xs text-gray-500">Costs cover selected work over its lifetime, including retained unknown outcomes.</p>
    </section>
    <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
      <h3 className="font-semibold text-white">Recorded work</h3>
      {projection.snapshot.work.length === 0 && <p className="text-sm text-gray-400">No work selected in this snapshot.</p>}
      {projection.snapshot.work.map(row => <div key={row.work.task_id} className="border-t border-gray-800 pt-3 space-y-2">
        <Link className="text-sm text-indigo-400 underline" to={`/company/work/${row.work.task_id}`}>Review current work {row.work.task_id.slice(0, 8)}</Link>
        <div className="flex flex-wrap gap-2"><StateLabel>{row.execution_state.replace(/_/g, ' ')}</StateLabel>
          <StateLabel>Acceptance: {row.acceptance}</StateLabel><StateLabel warn={row.billing === 'unconfirmed'}>Billing: {row.billing}</StateLabel></div>
        <p className="text-xs text-gray-400">Recorded receipt: {projection.receipt_task_ids.includes(row.work.task_id) ? 'Available' : 'Absent'}</p>
      </div>)}
      {report.data.blockers.length > 0 && <div><h4 className="text-sm text-amber-500">Recorded blockers</h4>
        <ul className="list-disc pl-5 text-sm text-gray-400">{report.data.blockers.map(reason => <li key={reason}>{reason}</li>)}</ul></div>}
    </section>
    <ReportPreparationPanel key={report.report_id} report={report} />
    <details className="rounded-lg border border-gray-800 bg-gray-900 p-5"><summary className="cursor-pointer text-sm text-gray-300">Recorded report and evidence pins</summary>
      <pre className="mt-4 text-xs text-gray-400 whitespace-pre-wrap break-all">{JSON.stringify(report, null, 2)}</pre></details>
  </div>
}
