import { useState } from 'react'
import { CompanyQueryState, instant, money, StateLabel } from '@/components/company/CompanyStatus'
import { Button } from '@/components/ui/button'
import { useCompanyCycleCosts } from '@/hooks/useCompanyCycleCosts'
import type { CycleCostSnapshot } from '@/types/companyCoding'

export function CycleCostContent({ data }: { data: CycleCostSnapshot }) {
  const totals = data.totals
  const complete = data.complete_membership && data.profile_bound && data.blockers.length === 0
    && totals.unconfirmed_action_ids.length === 0
  return <div className="space-y-4">
    <p className="text-xs text-gray-500">Current lifetime ledger observed {instant(data.observed_at)}. These figures do not indicate company completion.</p>
    <StateLabel warn={!complete}>{complete ? 'Registered cycle accounted for' : 'Incomplete cycle evidence'}</StateLabel>
    <div className="grid gap-4 sm:grid-cols-3 text-sm">
      <p className="text-gray-400">Recorded native spend<br /><strong className="text-white">{money(totals.known_spent_usd)}</strong></p>
      <p className="text-gray-400">Held reservation<br /><strong className="text-white">{totals.held_usd === null ? 'Unknown' : money(totals.held_usd)}</strong></p>
      <p className="text-gray-400">Confirmed cycle total<br /><strong className="text-white">{!complete || totals.actual_total_usd === null ? 'Incomplete' : money(totals.actual_total_usd)}</strong></p>
    </div>
    {data.blockers.length > 0 ? <ul className="list-disc pl-5 text-xs text-amber-500">{data.blockers.map(reason => <li key={reason}>{reason.replace(/_/g, ' ')}</li>)}</ul> : null}
    {data.charges.map(row => <article key={row.action_id} className="border-t border-gray-800 pt-3 space-y-2 text-sm">
      <div className="flex flex-wrap gap-2"><StateLabel>{row.attempt_kind.replace(/_/g, ' ')}</StateLabel>
        <StateLabel warn={row.confirmation === 'unconfirmed'}>{row.confirmation}</StateLabel>
        {row.native_state ? <StateLabel>{row.native_state.replace(/_/g, ' ')}</StateLabel> : null}</div>
      <p className="text-gray-400">Recorded charge: {row.ledger_actual_usd === null ? 'Unknown' : money(row.ledger_actual_usd)}</p>
      {row.blockers.length > 0 ? <ul className="list-disc pl-5 text-xs text-amber-500">{row.blockers.map(reason => <li key={reason}>{reason.replace(/_/g, ' ')}</li>)}</ul> : null}
    </article>)}
  </div>
}

function CycleCostRead({ company, expectedTask }: { company: string; expectedTask: string }) {
  const query = useCompanyCycleCosts(company)
  if (query.isPending || query.isError || !query.data) return <CompanyQueryState pending={query.isPending}
    error={query.error} refresh={() => { void query.refetch() }} />
  if (query.data.company_id !== company || !query.data.expected_task_ids.includes(expectedTask)) {
    return <CompanyQueryState pending={false} error={new Error('This record belongs to a different operating cycle.')} />
  }
  return <div className="space-y-4"><Button variant="outline" disabled={query.isFetching} onClick={() => { void query.refetch() }}>Refresh cycle finances</Button>
    <CycleCostContent data={query.data} /></div>
}

export function CompanyCycleCosts({ company, expectedTask }: { company: string; expectedTask: string }) {
  const [open, setOpen] = useState(false)
  return <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4" aria-label="Current cycle finances">
    <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold text-white">Current cycle finances</h3>
      <Button variant="outline" onClick={() => setOpen(value => !value)}>{open ? 'Close cycle finances' : 'Inspect cycle finances'}</Button></div>
    {open ? <CycleCostRead company={company} expectedTask={expectedTask} /> : <p className="text-sm text-gray-400">Inspect registered work, retained charges and reservations across the current company cycle.</p>}
  </section>
}
