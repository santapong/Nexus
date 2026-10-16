import { companyFetch } from '@/api/company'
import type { PreparedQualification, QualificationDispatchRecord, QualificationRecipeView,
  QualificationResultView, QualificationStatus } from '@/types/companyQualification'

const base = (company: string) => '/api/v2/companies/' + encodeURIComponent(company) + '/model-qualification'
const action = (company: string, id: string) => base(company) + '/actions/' + encodeURIComponent(id)

export const companyQualificationApi = {
  recipes: (company: string) => companyFetch<QualificationRecipeView[]>(base(company) + '/recipes'),
  prepare: (company: string, recipe: string) => companyFetch<PreparedQualification>(base(company) + '/prepare',
    { method: 'POST', body: JSON.stringify({ recipe_id: recipe }) }),
  status: (company: string, id: string) => companyFetch<QualificationStatus>(action(company, id)),
  result: (company: string, id: string) => companyFetch<QualificationResultView>(action(company, id) + '/result'),
  dispatch: (company: string, id: string, hash: string) => companyFetch<QualificationDispatchRecord>(action(company, id) + '/dispatch',
    { method: 'POST', body: JSON.stringify({ expected_hash: hash }) }),
}
