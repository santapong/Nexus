import { companyFetch } from '@/api/company'
import type { PlanningInputReview } from '@/types/companyPlanning'

export const companyPlanningApi = {
  input: (company: string, action: string) => companyFetch<PlanningInputReview>(
    `/api/v2/companies/${encodeURIComponent(company)}/planning/actions/${encodeURIComponent(action)}/input`,
    { method: 'GET', cache: 'no-store' }),
}
