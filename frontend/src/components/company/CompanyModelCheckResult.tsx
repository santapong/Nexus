import { instant, money, StateLabel } from '@/components/company/CompanyStatus'
import { qualificationLabels, qualificationPhase } from '@/hooks/companyQualificationState'
import type { QualificationResultView, QualificationStatus } from '@/types/companyQualification'

export function CompanyModelCheckResult({ status, result }: {
  status: QualificationStatus; result: QualificationResultView | undefined
}) {
  const phase = qualificationPhase(status)
  const billingUnknown = status.hold?.state === 'unknown' || status.effect?.state === 'outcome_unknown'
  const matches = result?.availability === 'available' && result.sha256 != null
    && status.effect?.evidence_sha256s?.includes(result.sha256) === true
    && result.native_outcome === status.effect?.state
  const provider = matches && result ? result.provider_result : null
  return <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4" aria-label="Recorded model check">
    <div className="flex flex-wrap justify-between gap-3"><h3 className="font-semibold text-white">Recorded result</h3>
      <StateLabel warn={phase === 'unknown' || phase === 'stopped'}>{qualificationLabels[phase]}</StateLabel></div>
    {billingUnknown ? <p role="status" className="text-sm text-amber-500">
      Usage unconfirmed. The reservation remains held for reconciliation.</p> : null}
    <dl className="grid gap-3 text-sm sm:grid-cols-2">
      <div><dt className="text-gray-400">Reservation</dt><dd className="text-gray-200">{money(status.hold?.amount_usd ?? status.action.proposal.estimated_cost_usd)}</dd></div>
      <div><dt className="text-gray-400">Recorded usage cost</dt><dd className="text-gray-200">{money(status.hold?.actual_usd)}</dd></div>
      {status.hold ? <div><dt className="text-gray-400">Budget day</dt><dd className="text-gray-200">{status.hold.day} · Asia/Bangkok</dd></div> : null}
      {result?.captured_at ? <div><dt className="text-gray-400">Response captured</dt><dd className="text-gray-200">{instant(result.captured_at)}</dd></div> : null}
    </dl>
    {provider ? <div className="space-y-3">
      {provider.error_code ? <p className="text-sm text-amber-500">Recorded issue: {provider.error_code.replace(/_/g, ' ')}</p> : null}
      {provider.structured_json || provider.text ? <pre className="max-h-80 overflow-auto rounded-lg border border-gray-800 bg-gray-950 p-4 text-sm text-gray-300 whitespace-pre-wrap break-words"
        aria-label="Saved model response">{provider.structured_json ?? provider.text}</pre> :
        <p className="text-sm text-gray-400">No response content was recorded.</p>}
      <p className="font-mono text-xs break-all text-gray-500">Evidence {result?.sha256}</p>
    </div> : <p className="text-sm text-gray-400">{status.effect
      ? 'Saved response details are unavailable from the current receipt. Refresh to check the recorded result.'
      : 'A saved response will appear here after a recorded attempt.'}</p>}
    <p className="text-xs text-gray-500">Model activation requires a separate quality review.</p>
  </section>
}
