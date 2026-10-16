import { money } from '@/components/company/CompanyStatus'
import type { PlanningInputReview } from '@/types/companyPlanning'

export function CompanyPlanningInput({ data }: { data: PlanningInputReview }) {
  const request = data.prepared.request
  return <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
    <div><h3 className="font-semibold text-white">Review the planning input</h3>
      <p className="text-sm text-gray-400 mt-2">Nexus will send these instructions and source excerpts to {data.provider} to draft a plan.</p></div>
    <div className="grid gap-3 sm:grid-cols-2 text-sm"><p className="text-gray-400">Model <span className="text-gray-200">{data.model_id}</span></p>
      <p className="text-gray-400">Maximum reservation <strong className="text-gray-200">{money(data.maximum_reservation_usd)}</strong></p></div>
    <p className="text-xs text-gray-400">Requested output limit {request.bounds.max_output_tokens} tokens. Actual usage is recorded after the response.</p>
    <div><p className="text-sm font-medium text-gray-200 mb-2">Task and source excerpts</p>
      <pre aria-label="Exact planning input" className="max-h-80 overflow-auto rounded-lg border border-gray-800 bg-gray-950 p-4 text-sm text-gray-300 whitespace-pre-wrap break-words">{request.input_text}</pre></div>
    <details className="text-sm text-gray-400"><summary className="cursor-pointer">Company instructions and registered goal</summary>
      <pre aria-label="Exact planning instructions" className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words">{request.system_text}</pre></details>
    {request.output_schema ? <details className="text-xs text-gray-500"><summary className="cursor-pointer">Required response structure</summary>
      <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap break-all">{request.output_schema.schema_json}</pre></details> : null}
    <p className="text-sm text-gray-400">The response is a draft for review. Approving this request does not approve the resulting plan.</p>
    <details className="text-xs text-gray-500"><summary className="cursor-pointer">Review identifiers</summary>
      <div className="mt-3 space-y-2 font-mono break-all"><p>Proposal {data.proposal_sha256}</p>
        <p>Input {data.request_sha256}</p><p>Saved preparation {data.descriptor_sha256}</p></div></details>
  </section>
}
