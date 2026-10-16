import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { RefreshCw, ShieldCheck } from 'lucide-react'
import { Sidebar } from '@/components/layout/Sidebar'
import { Button } from '@/components/ui/button'
import { useCompanyIdentity } from '@/hooks/useCompany'
import type { CompanyIdentity } from '@/types/company'
import { CompanyApiError, companySessionVersion, setCompanySessionToken } from '@/api/company'

export function CompanyLayout() {
  const [dark, setDark] = useState(() => localStorage.getItem('nexus-theme') !== 'light')
  const identity = useCompanyIdentity()
  const client = useQueryClient()
  const navigate = useNavigate()
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    document.documentElement.classList.toggle('light-mode', !dark)
    localStorage.setItem('nexus-theme', dark ? 'dark' : 'light')
  }, [dark])
  const current = identity.data
  const owner = current && current.membership_role === 'owner' && current.principal_id === current.owner_id
    && current.company_active && current.workspace_active && current.principal_active && current.membership_active
  const refresh = () => { void client.invalidateQueries({ queryKey: ['company-identity'] });
    void client.invalidateQueries({ queryKey: ['company'] }) }
  const signOut = () => {
    setCompanySessionToken(null)
    client.clear()
    navigate('/company/login', { replace: true })
  }
  return <div className="min-h-screen bg-gray-950 text-gray-100">
    <Sidebar dark={dark} onToggleTheme={() => setDark(value => !value)} companyOnly />
    <div className="md:pl-60">
      <header className="border-b border-gray-800 px-6 py-5 flex items-center justify-between gap-4">
        <div className="ml-10 md:ml-0"><p className="text-xs text-gray-400 mb-1">NEXUS / Company</p>
          <h1 className="text-lg font-semibold text-white">Owner workspace</h1></div>
        <div className="flex gap-2"><Button variant="outline" size="sm" onClick={refresh} disabled={identity.isFetching}>
          <RefreshCw size={14} /> Refresh</Button>
          <Button variant="ghost" size="sm" onClick={signOut}>Sign out</Button></div>
      </header>
      <main className="max-w-6xl mx-auto p-4 md:p-6 space-y-6">
        {import.meta.env.VITE_COMPANY_UAT === 'true' && <p role="status"
          className="text-xs text-amber-500 border border-amber-700/40 rounded-lg px-4 py-3">
          Local supervised UAT · disposable task profile</p>}
        {identity.isPending ? <p role="status" className="text-gray-400">Checking your current company access…</p>
          : identity.isError ? <div role="alert" className="rounded-lg border border-gray-800 bg-gray-900 p-6 space-y-3">
            <h2 className="text-lg font-semibold text-white">Company access unavailable</h2>
            <p className="text-gray-400">{identity.error instanceof CompanyApiError && identity.error.status === 401
              ? 'Sign in with your company account to continue.' : identity.error.message}</p>
            <Link className="text-indigo-400 underline" to="/company/login">Sign in</Link></div>
          : !owner ? <div role="alert" className="rounded-lg border border-gray-800 bg-gray-900 p-6">
            <h2 className="font-semibold text-white">Owner access required</h2>
            <p className="text-gray-400 mt-2">This workspace is available to the current company owner.</p></div>
          : <>
            <div className="flex flex-wrap gap-3 items-center justify-between text-xs text-gray-400">
              <span className="flex items-center gap-2"><ShieldCheck size={15} className="text-indigo-400" /> Current owner access</span>
              <span className="font-mono break-all">Company {current.company_id}</span></div>
            <nav aria-label="Company views" className="flex flex-wrap gap-1 border-b border-gray-800">
              {[['Today', '/company/today'], ['Knowledge', '/company/knowledge'], ['Company', '/company/overview'], ['Approvals', '/company/approvals']].map(([label, to]) =>
                <NavLink key={to} to={to} className={({ isActive }) => `px-4 py-3 text-sm border-b-2 ${isActive
                  ? 'border-indigo-500 text-white' : 'border-transparent text-gray-400 hover:text-gray-100'}`}>{label}</NavLink>)}
            </nav>
            {identity.isFetching && <p role="status" className="text-sm text-gray-400">Rechecking company access… Changes are paused and your current draft is preserved.</p>}
            <fieldset key={`${current.company_id}:${current.principal_id}:${companySessionVersion()}`} disabled={identity.isFetching} className="min-w-0" aria-busy={identity.isFetching}>
              <Outlet context={current satisfies CompanyIdentity} />
            </fieldset>
          </>}
      </main>
    </div>
  </div>
}
