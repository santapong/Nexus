import { money } from '@/components/company/CompanyStatus'
import type { CodingInputReview } from '@/types/companyCoding'

export function CompanyCodingInput({ data }: { data: CodingInputReview }) {
  const request = data.prepared.request
  return <section className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
    <div><h3 className="font-semibold text-white">Review the coding input</h3>
      <p className="text-sm text-gray-400 mt-2">Nexus will send these instructions and source excerpts to {data.model.provider} to propose a code change.</p></div>
    <div className="grid gap-3 sm:grid-cols-2 text-sm"><p className="text-gray-400">Model <span className="text-gray-200">{data.model.model_id}</span></p>
      <p className="text-gray-400">Maximum reservation <strong className="text-gray-200">{money(data.maximum_reservation_usd)}</strong></p></div>
    <p className="text-xs text-gray-400">Requested output limit {request.bounds.max_output_tokens} tokens.</p>
    <div><h4 className="text-sm font-medium text-gray-200 mb-2">Task and complete source input</h4>
      <pre aria-label="Exact coding input" className="max-h-96 overflow-auto rounded-lg bg-gray-950 p-4 text-sm text-gray-300 whitespace-pre-wrap break-words">{request.input_text}</pre></div>
    <details className="text-sm text-gray-400"><summary className="cursor-pointer">Company coding instructions</summary>
      <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words">{request.system_text}</pre></details>
    <div className="text-sm text-gray-400"><h4 className="font-medium text-gray-200">Allowed file changes</h4>
      <ul className="list-disc pl-5 mt-2">{data.prepared.binding.allowed_write_paths.map(path => <li key={path} className="break-all">{path}</li>)}</ul></div>
    {request.output_schema ? <details className="text-xs text-gray-500"><summary className="cursor-pointer">Required response structure</summary>
      <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap break-all">{request.output_schema.schema_json}</pre></details> : null}
    <p className="text-sm text-gray-400">Approving this request allows a model response. The proposed patch still needs separate building and independent verification.</p>
    <details className="text-xs text-gray-500"><summary className="cursor-pointer">Review identifiers</summary>
      <div className="mt-3 space-y-2 font-mono break-all"><p>Proposal {data.proposal_sha256}</p>
        <p>Input {data.request_sha256}</p><p>Saved header {data.header_sha256}</p></div></details>
  </section>
}
