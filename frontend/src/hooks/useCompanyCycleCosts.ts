import { useQuery } from '@tanstack/react-query'
import { companySessionVersion } from '@/api/company'
import { companyCycleCostApi } from '@/api/companyCycleCosts'

export function useCompanyCycleCosts(company: string) {
  return useQuery({ queryKey: ['company', company, 'cycle-costs', companySessionVersion()],
    queryFn: () => companyCycleCostApi.read(company), retry: false, staleTime: 0, gcTime: 0 })
}
