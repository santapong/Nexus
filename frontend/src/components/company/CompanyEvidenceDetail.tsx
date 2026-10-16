import { useCompanyEvidence } from '@/hooks/useCompanyKnowledge'
import { CompanyQueryState, instant, StateLabel } from '@/components/company/CompanyStatus'
import { CompanyGoalDraft } from '@/components/company/CompanyGoalDraft'
import type { CompanyIdentity } from '@/types/company'

export function CompanyEvidenceDetail({ identity, evidenceId, revalidating = false }: { identity: CompanyIdentity; evidenceId: string; revalidating?: boolean }) {
  const query = useCompanyEvidence(identity.company_id, evidenceId)
  if (query.isPending || query.isError || !query.data)
    return <CompanyQueryState pending={query.isPending} error={query.error} refresh={() => { void query.refetch() }} />
  const evidence = query.data, event = evidence.record.source_event
  return <div className="space-y-5" aria-busy={query.isFetching || revalidating}>
    {(query.isFetching || revalidating) && <p role="status" className="text-sm text-gray-400">Refreshing citation and search access… Your goal draft is preserved; saving is paused.</p>}
    <section aria-label="Citation details" className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
      <div className="flex flex-wrap gap-2 justify-between"><h3 className="font-semibold text-white">{evidence.external_key}</h3>
        <div className="flex gap-2"><StateLabel warn={evidence.source_state !== 'current'}>{evidence.source_state}</StateLabel>
          <StateLabel warn={evidence.freshness !== 'fresh'}>{evidence.freshness}</StateLabel></div></div>
      <p className="text-xs text-gray-400">Source {evidence.source_symbol} · {evidence.data_classification}</p>
      <p className="text-xs text-gray-400">Source date: {event.value ?? 'Unknown'} ({event.precision}) · {event.basis}</p>
      <p className="text-xs text-gray-500">Ingested {instant(evidence.record.ingested_at)}. Access and source state were checked for this read.</p>
      <pre className="rounded-md bg-gray-950 p-4 text-sm text-gray-200 whitespace-pre-wrap break-words">{evidence.text}</pre>
      <details className="text-xs text-gray-400"><summary className="cursor-pointer">Citation provenance</summary>
        <dl className="mt-3 space-y-2 break-all"><div><dt>Evidence</dt><dd>{evidence.record.evidence_id}</dd></div>
          <div><dt>Source revision</dt><dd>{evidence.record.source.revision}</dd></div>
          <div><dt>UTF-8 span</dt><dd>{evidence.record.raw_span.start_byte}–{evidence.record.raw_span.end_byte}</dd></div>
          <div><dt>Span SHA256</dt><dd>{evidence.record.span_sha256}</dd></div></dl>
      </details>
    </section>
    <CompanyGoalDraft key={`${identity.company_id}:${evidenceId}`} identity={identity} evidence={evidence} revalidating={query.isFetching || revalidating} />
  </div>
}
