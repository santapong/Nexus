import { companyFetch } from '@/api/company'
import type { CycleCostSnapshot } from '@/types/companyCoding'

export const companyCycleCostApi = {
  read: (company: string) => companyFetch<CycleCostSnapshot>(
    `/api/v2/companies/${encodeURIComponent(company)}/management/cycle-costs`, { method: 'GET', cache: 'no-store' }),
}
