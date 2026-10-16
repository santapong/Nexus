import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { instant, money } from '@/components/company/CompanyStatus'
import { CompanyModelCheckResult } from '@/components/company/CompanyModelCheckResult'
import { canDecideQualification, canDispatchQualification } from '@/hooks/companyQualificationState'
import { useDecideModelCheck, useDispatchModelCheck, useQualificationResult } from '@/hooks/useCompanyQualification'
import type { QualificationStatus } from '@/types/companyQualification'

export function CompanyModelCheckAction({ company, status, paused, refreshing, refresh, result }: {
  company: string; status: QualificationStatus; paused: boolean; refreshing: boolean; refresh: () => void
  result: ReturnType<typeof useQualificationResult>
}) {
  const [reviewed, setReviewed] = useState(false)
  const action = status.action.proposal.action_id
  const decision = useDecideModelCheck(company, action, status.action.proposal_hash)
  const dispatch = useDispatchModelCheck(company, action, status.action.proposal_hash)
  const pending = refreshing || decision.isPending || dispatch.isPending
  const recipe = status.recipe
  const approval = status.action.approval
  const confirm = canDecideQualification(status, paused, true)
  const reject = canDecideQualification(status, paused, false)
  return <div className="space-y-5">
    <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
      <div className="flex flex-wrap justify-between gap-3"><div><h3 className="font-semibold text-white">Review this check</h3>
        <p className="text-sm text-gray-400 mt-1">{recipe.provider} · {recipe.model_id}</p></div>
        <Button variant="outline" size="sm" disabled={pending || result.isFetching}
          onClick={() => { refresh(); void result.refetch() }}>Refresh check</Button></div>
      <p className="text-sm text-gray-300">Maximum reservation: <strong>{money(status.action.proposal.estimated_cost_usd)}</strong></p>
      <p className="text-xs text-gray-400">This amount is reserved at dispatch. Usage cost is recorded separately after the response.</p>
      <div className="space-y-2"><p className="text-sm font-medium text-gray-200">Public check input</p>
        <pre className="max-h-64 overflow-auto rounded-lg border border-gray-800 bg-gray-950 p-4 text-sm text-gray-300 whitespace-pre-wrap break-words">{recipe.input_text}</pre>
        {recipe.system_text ? <details className="text-sm text-gray-400"><summary className="cursor-pointer">Additional check instructions</summary>
          <pre className="mt-3 whitespace-pre-wrap break-words">{recipe.system_text}</pre></details> : null}
        <p className="text-xs text-gray-500">{recipe.output_schema ? 'Structured JSON response' : 'Text response'} · Requested output limit {recipe.request_output_cap} tokens</p></div>
      {refreshing ? <p role="status" className="text-sm text-gray-400">Refreshing current approval and usage. Changes are paused.</p> : null}
      {paused ? <p role="status" className="text-sm text-amber-500">Company intake is paused.</p> : null}
      {status.work.state === 'outcome_unknown' ? <p role="status" className="text-sm text-amber-500">
        This work has an unresolved attempt. Review it before dispatching more checks.</p> : null}
      {confirm || reject ? <>
        <label className="flex items-start gap-3 text-sm text-gray-300"><input type="checkbox" className="mt-1 accent-indigo-500"
          checked={reviewed} disabled={pending} onChange={event => setReviewed(event.target.checked)} />
          I reviewed the public input and maximum reservation for this check.</label>
        <div className="flex flex-wrap gap-3"><Button disabled={!reviewed || pending || !confirm}
          onClick={() => decision.mutate(true)}>Approve check</Button>
          <Button variant="outline" disabled={!reviewed || pending || !reject}
            onClick={() => decision.mutate(false)}>Reject check</Button></div>
      </> : null}
      {approval ? <p className="text-sm text-gray-400">Owner decision: {approval.decision} · expires {instant(approval.expires_at)}</p> : null}
      {canDispatchQualification(status, paused) ? <Button disabled={pending} onClick={() => dispatch.mutate()}>Dispatch approved check</Button> : null}
      {decision.isError ? <p role="alert" className="text-sm text-red-400">{decision.error.message}</p> : null}
      {dispatch.isError ? <p role="alert" className="text-sm text-red-400">{dispatch.error.message}</p> : null}
      {decision.isSuccess ? <p role="status" className="text-sm text-emerald-500">Owner decision saved.</p> : null}
      {dispatch.isSuccess ? <p role="status" className="text-sm text-gray-300">Dispatch recorded. Refresh to inspect the worker result.</p> : null}
      <details className="text-xs text-gray-500"><summary className="cursor-pointer">Audit identity</summary>
        <div className="mt-3 space-y-2 font-mono break-all"><p>Proposal {status.action.proposal_hash}</p>
          <p>Check {action}</p><p>Recipe {recipe.recipe_sha256}</p></div></details>
    </section>
    {result.isError ? <p role="alert" className="text-sm text-amber-500">Saved response is unavailable: {result.error.message}</p> : null}
    <CompanyModelCheckResult status={status} result={result.isError ? undefined : result.data} />
  </div>
}
