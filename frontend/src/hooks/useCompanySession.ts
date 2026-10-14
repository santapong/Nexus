import { useMutation, useQueryClient } from '@tanstack/react-query'
import { companyApi, companySessionVersion, setCompanySessionToken } from '@/api/company'
import type { CompanyLogin, CompanySignup } from '@/types/company'

export function useCompanySession() {
  const client = useQueryClient()
  return useMutation({ mutationFn: async (request: CompanyLogin | CompanySignup) => {
    const session = 'invitation' in request ? await companyApi.signup(request) : await companyApi.login(request)
    await client.cancelQueries()
    client.clear()
    setCompanySessionToken(session.access_token)
    const version = companySessionVersion()
    try {
      const identity = await companyApi.identity()
      client.setQueryData(['company-identity', companySessionVersion()], identity)
      return identity
    } catch (error) {
      if (companySessionVersion() === version) setCompanySessionToken(null)
      throw error
    }
  } })
}
