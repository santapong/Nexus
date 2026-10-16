import { useState, type FormEvent } from 'react'
import { useOutletContext } from 'react-router-dom'
import { Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { CompanyEvidenceDetail } from '@/components/company/CompanyEvidenceDetail'
import { CompanyQueryState, instant } from '@/components/company/CompanyStatus'
import { useCompanyKnowledge } from '@/hooks/useCompanyKnowledge'
import { citationSummaries, searchRequest } from '@/hooks/companyGoalDraft'
import type { CompanyIdentity } from '@/types/company'

export function CompanyKnowledgePage() {
  const identity = useOutletContext<CompanyIdentity>()
  const [input, setInput] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const query = useCompanyKnowledge(identity.company_id, search)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    try {
      const next = searchRequest(input).search.query
      if (next === search) void query.refetch()
      else setSearch(next)
      setSelected(null); setError(null)
    }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Review your search.') }
  }
  const citations = query.data ? citationSummaries(query.data, identity.company_id) : []
  return <div className="space-y-6">
    <div><h2 className="text-2xl font-semibold text-white">Knowledge</h2>
      <p className="text-gray-400 mt-2">Find company evidence, inspect its source and use a current citation to frame a goal.</p></div>
    <form onSubmit={submit} className="flex flex-wrap gap-3">
      <label htmlFor="knowledge-search" className="sr-only">Search company knowledge</label>
      <Input id="knowledge-search" className="flex-1 min-w-48" value={input} onChange={event => setInput(event.target.value)} placeholder="Search Nexus documents and operating evidence" />
      <Button type="submit" disabled={query.isFetching}><Search size={16} /> Search</Button>
    </form>
    {error && <p role="alert" className="text-sm text-amber-400">{error}</p>}
    {!search && <p className="text-sm text-gray-400">Search to find current, permitted evidence. Results are citations, not verified conclusions.</p>}
    {search && (query.isPending || query.isError) ? <CompanyQueryState pending={query.isPending} error={query.error} refresh={() => { void query.refetch() }} />
      : search && <section aria-label="Search results" className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-3">
        {query.isFetching && <p role="status" className="text-sm text-gray-400">Refreshing search results…</p>}
        <h3 className="font-semibold text-white">{citations.length} citations for “{search}”</h3>
        {citations.length === 0 && !query.data?.handles.length && <p className="text-sm text-gray-400">No current evidence is available for this search and your permissions. Try another term.</p>}
        {query.data && citations.length < query.data.handles.length && <p role="status" className="text-sm text-amber-400">Some citation metadata could not be displayed. Refresh before relying on these results.</p>}
        {citations.map(citation => <button key={citation.evidenceId} type="button" disabled={query.isFetching} onClick={() => setSelected(citation.evidenceId)}
          aria-pressed={selected === citation.evidenceId} className={`block w-full text-left rounded-md border p-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${selected === citation.evidenceId ? 'border-indigo-500 bg-gray-800' : 'border-gray-800 hover:border-gray-600'}`}>
          <span className="block text-sm text-indigo-300">{citation.label}</span>
          <span className="block text-xs text-gray-400 mt-2">Source date: {citation.sourceDate} · Ingested {instant(citation.ingestedAt)}</span>
        </button>)}
        {query.data?.truncated && <p className="text-xs text-amber-400">Results are bounded. Narrow your search to find more relevant evidence.</p>}
      </section>}
    {selected && !query.isError && <CompanyEvidenceDetail key={`${identity.company_id}:${selected}`} identity={identity} evidenceId={selected} revalidating={query.isFetching} />}
  </div>
}
