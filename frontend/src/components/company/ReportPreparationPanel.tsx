import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCompanyView } from '@/hooks/useCompany'
import { useReportPreparation } from '@/hooks/useCompanyReports'
import type { SavedOperatingReport } from '@/types/company'
import { CompanyQueryState, instant } from './CompanyStatus'

export function ReportPreparationPanel({ report }: { report: SavedOperatingReport }) {
  const company = useCompanyView(report.company_id)
  const [commitment, setCommitment] = useState(''), [evidence, setEvidence] = useState('')
  const action = useReportPreparation(report.company_id, report.report_id)
  if (company.isPending || company.isError) return <CompanyQueryState pending={company.isPending}
    error={company.error} refresh={() => { void company.refetch() }} />
  const rows = company.data.commitments.filter(item => item.binding_state === 'current'
    && item.revision.definition.plan.plan_revision_id === report.selection.plan.plan_revision_id)
  const profile = action.resolve.data
  return <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
    <div><h3 className="font-semibold text-white">Prepare the report action</h3>
      <p className="text-xs text-gray-400 mt-2">Choose a current commitment and existing Brain evidence. Preparation records a pending action for your review.</p></div>
    <form onSubmit={event => { event.preventDefault(); action.select(commitment, evidence) }} className="space-y-4">
      <fieldset disabled={Boolean(profile) || action.resolve.isPending || company.data.paused} className="space-y-4">
        <label className="block space-y-2 text-sm text-gray-300">Current commitment
          <select required value={commitment} onChange={event => setCommitment(event.target.value)}
            className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2">
            <option value="">Choose a commitment for this report plan</option>
            {rows.map(item => <option key={item.revision.commitment_id} value={item.revision.commitment_id}>{item.revision.definition.deliverable}</option>)}
          </select></label>
        <label className="block space-y-2 text-sm text-gray-300">Brain evidence artifact IDs
          <Input value={evidence} onChange={event => setEvidence(event.target.value)} required maxLength={1216}
            placeholder="Separate existing artifact IDs with commas" /></label>
        <Button type="submit">{action.resolve.isPending ? 'Checking selection…' : 'Check report selection'}</Button>
      </fieldset>
    </form>
    {profile && <div className="space-y-3"><p className="text-xs text-gray-400">Actionable at {instant(profile.due.actionable_at)}</p>
      <Button disabled={company.data.paused || action.prepare.isPending || action.prepare.isSuccess}
        onClick={() => action.prepare.mutate(profile.reference)}>{action.prepare.isPending ? 'Preparing…' : 'Prepare pending author action'}</Button>
      <Button variant="outline" disabled={action.prepare.isPending} onClick={action.reset}>Choose another selection</Button></div>}
    {(action.error || action.resolve.isError || action.prepare.isError) && <p role="alert" className="text-sm text-red-400">
      {action.error ?? action.resolve.error?.message ?? action.prepare.error?.message}</p>}
    {action.prepare.data && <div role="status" className="space-y-2"><p className="text-sm text-gray-300">Pending action recorded. Your exact approval is required.</p>
      <Link to={`/company/actions/${action.prepare.data.action.proposal.action_id}`} className="text-sm text-indigo-400 underline">Review the exact action</Link></div>}
    {rows.length === 0 && <p className="text-xs text-gray-400">No current commitment for this plan appears in this page. Review the company’s commitments before preparing.</p>}
  </section>
}
