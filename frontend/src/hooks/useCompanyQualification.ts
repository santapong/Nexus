import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { companySessionVersion } from '@/api/company'
import { companyQualificationApi } from '@/api/companyQualification'
import { decideQualification, dispatchQualification } from '@/hooks/companyQualificationActions'

export function useQualificationRecipes(company: string, enabled = true) {
  return useQuery({ queryKey: ['company', company, 'model-checks', 'recipes', companySessionVersion()],
    queryFn: () => companyQualificationApi.recipes(company), enabled, retry: false, staleTime: 0 })
}

export function useQualificationStatus(company: string, action: string | undefined) {
  return useQuery({ queryKey: ['company', company, 'model-checks', action, companySessionVersion()],
    queryFn: () => companyQualificationApi.status(company, action!), enabled: Boolean(action), retry: false, staleTime: 0 })
}

export function useQualificationResult(company: string, action: string | undefined) {
  return useQuery({ queryKey: ['company', company, 'model-checks', action, 'result', companySessionVersion()],
    queryFn: () => companyQualificationApi.result(company, action!), enabled: Boolean(action), retry: false, staleTime: 0 })
}

export function usePrepareModelCheck(company: string) {
  const client = useQueryClient()
  return useMutation({ mutationFn: async (recipe: string) => {
    const prepared = await companyQualificationApi.prepare(company, recipe)
    if (prepared.action.company_id !== company || prepared.action.proposal.company_id !== company) {
      throw new Error('The prepared check belongs to another company. Refresh your current workspace.')
    }
    return prepared
  }, onSuccess: async () => { await client.invalidateQueries({ queryKey: ['company', company] }) } })
}

export function useDecideModelCheck(company: string, action: string, hash: string) {
  const client = useQueryClient()
  return useMutation({ mutationFn: (approved: boolean) => decideQualification(company, action, hash, approved),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['company', company] }) } })
}

export function useDispatchModelCheck(company: string, action: string, hash: string) {
  const client = useQueryClient()
  return useMutation({ mutationFn: () => dispatchQualification(company, action, hash),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['company', company] }) } })
}
