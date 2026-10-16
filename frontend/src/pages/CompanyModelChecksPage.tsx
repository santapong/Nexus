import { Link, useNavigate, useOutletContext, useParams } from 'react-router-dom'
import { CompanyApiError } from '@/api/company'
import { Button } from '@/components/ui/button'
import { CompanyModelCheckAction } from '@/components/company/CompanyModelCheckAction'
import { CompanyQueryState, instant, money } from '@/components/company/CompanyStatus'
import { requireQualificationReview } from '@/hooks/companyQualificationState'
import { usePrepareModelCheck, useQualificationRecipes, useQualificationResult, useQualificationStatus } from '@/hooks/useCompanyQualification'
import { useCompanyView } from '@/hooks/useCompany'
import type { CompanyIdentity } from '@/types/company'

function CheckDetail({ company, action, paused, query, result }: {
  company: string; action: string; paused: boolean
  query: ReturnType<typeof useQualificationStatus>; result: ReturnType<typeof useQualificationResult>
}) {
  if (query.isPending || query.isError || !query.data) return <CompanyQueryState pending={query.isPending}
    error={query.error} refresh={() => { void query.refetch() }} />
  try { requireQualificationReview(query.data, company, action, query.data.action.proposal_hash) }
  catch (error) { return <CompanyQueryState pending={false} error={error instanceof Error ? error : new Error('Check unavailable')} /> }
  return <CompanyModelCheckAction key={query.data.action.proposal_hash} company={company} status={query.data}
    paused={paused} refreshing={query.isFetching} result={result} refresh={() => { void query.refetch() }} />
}

export function CompanyModelChecksPage() {
  const identity = useOutletContext<CompanyIdentity>()
  const { actionId } = useParams()
  const company = useCompanyView(identity.company_id)
  const recipes = useQualificationRecipes(identity.company_id, !actionId)
  const status = useQualificationStatus(identity.company_id, actionId)
  const result = useQualificationResult(identity.company_id, actionId)
  const prepare = usePrepareModelCheck(identity.company_id)
  const navigate = useNavigate()
  const unavailable = recipes.error instanceof CompanyApiError && [404, 503].includes(recipes.error.status)
  if (company.isPending || company.isError || !company.data) return <CompanyQueryState pending={company.isPending}
    error={company.error} refresh={() => { void company.refetch() }} />
  return <div className="space-y-5">
    <div><h2 className="text-2xl font-semibold text-white">Model checks</h2>
      <p className="text-gray-400 mt-2">Review an AI connection check, approve its reservation, then dispatch a bounded run.</p></div>
    {actionId ? <><Link className="text-sm text-indigo-400" to="/company/model-checks">All model checks</Link>
      <CheckDetail key={actionId} company={identity.company_id} action={actionId} query={status} result={result}
        paused={company.data.paused || company.isFetching} /></> :
      unavailable ? <section role="status" className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-3">
        <h3 className="font-semibold text-white">Model checks are unavailable</h3>
        <p className="text-sm text-gray-400">AI connection checks are not available in this workspace yet.</p>
        <Button variant="outline" onClick={() => { void recipes.refetch() }}>Refresh availability</Button></section> :
        recipes.isPending || recipes.isError || !recipes.data ? <CompanyQueryState pending={recipes.isPending}
          error={recipes.error} refresh={() => { void recipes.refetch() }} /> : <>
          {recipes.data.length === 0 ? <p role="status" className="text-sm text-gray-400">There are no configured model checks.</p> : null}
          <div className="grid gap-4 md:grid-cols-2">{recipes.data.map(recipe => <section key={recipe.recipe_sha256}
            className="rounded-lg border border-gray-800 bg-gray-900 p-5 space-y-4">
            <div><h3 className="font-semibold text-white">{recipe.provider} · {recipe.case_id}</h3>
              <p className="text-sm text-gray-400 mt-1">{recipe.model_id}</p></div>
            <p className="text-sm text-gray-300">Maximum reservation {money(recipe.maximum_reservation?.amount_usd)}</p>
            <p className="text-sm text-gray-400 line-clamp-3">{recipe.input_text}</p>
            <p className="text-xs text-gray-500">Check window ends {instant(recipe.expires_at)}</p>
            <Button disabled={prepare.isPending || recipes.isFetching || company.isFetching || company.data.paused || recipe.availability !== 'current'}
              onClick={() => prepare.mutate(recipe.recipe_id, { onSuccess: data => {
                navigate('/company/model-checks/actions/' + encodeURIComponent(data.action.proposal.action_id))
              } })}>Prepare for review</Button>
          </section>)}</div>
          <p className="text-xs text-gray-500">Preparation saves a reviewable proposal. You approve and dispatch it separately.</p>
        </>}
    {prepare.isError ? <p role="alert" className="text-sm text-red-400">{prepare.error.message}</p> : null}
  </div>
}
