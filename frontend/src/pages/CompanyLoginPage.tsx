import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useCompanySession } from '@/hooks/useCompanySession'

export function CompanyLoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [invitation, setInvitation] = useState('')
  const [signup, setSignup] = useState(false)
  const session = useCompanySession()
  const navigate = useNavigate()
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const body = { email: email.trim(), password }
    session.mutate(signup ? { ...body, invitation: invitation.trim() } : body,
      { onSuccess: () => { setPassword(''); setInvitation(''); navigate('/company/today', { replace: true }) } })
  }
  return <main className="min-h-screen bg-gray-950 text-gray-100 flex items-center justify-center p-5">
    <section className="w-full max-w-md border border-gray-800 bg-gray-900 rounded-xl p-6 sm:p-8 space-y-6">
      <div><p className="text-sm font-semibold tracking-widest text-indigo-400">NEXUS</p>
        <h1 className="text-2xl text-white font-semibold mt-3">Company sign in</h1>
        {import.meta.env.VITE_COMPANY_UAT === 'true' && <p className="text-xs text-amber-500 mt-2">Local supervised UAT · disposable task profile</p>}
        <p className="text-gray-400 text-sm mt-2">Review your supervised company plans, work and exact owner decisions.</p></div>
      <p className="text-xs text-gray-400 flex items-center gap-2"><ShieldCheck size={15} /> Access is checked against current company membership.</p>
      <form onSubmit={submit} className="space-y-4">
        <div><label htmlFor="company-email" className="block text-sm text-gray-300 mb-2">Email</label>
          <input id="company-email" type="email" autoComplete="username" required maxLength={254}
            value={email} onChange={event => setEmail(event.target.value)} className="w-full rounded-md border border-gray-700 bg-gray-950 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500" /></div>
        <div><label htmlFor="company-password" className="block text-sm text-gray-300 mb-2">Password</label>
          <input id="company-password" type="password" autoComplete={signup ? 'new-password' : 'current-password'}
            required minLength={12} maxLength={256} value={password} onChange={event => setPassword(event.target.value)}
            className="w-full rounded-md border border-gray-700 bg-gray-950 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500" /></div>
        {signup && <div><label htmlFor="company-invitation" className="block text-sm text-gray-300 mb-2">Task invitation</label>
          <input id="company-invitation" type="password" autoComplete="off" required minLength={32} maxLength={256}
            value={invitation} onChange={event => setInvitation(event.target.value)} className="w-full rounded-md border border-gray-700 bg-gray-950 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500" />
          <p className="text-xs text-gray-500 mt-2">An issued invitation is required to initialize this local supervised account.</p></div>}
        {session.isError && <p role="alert" className="text-sm text-red-400">{session.error.message}</p>}
        <Button type="submit" className="w-full" disabled={session.isPending}>
          {session.isPending ? 'Checking access…' : signup ? 'Initialize invited account' : 'Sign in'}</Button>
      </form>
      <div className="text-sm space-y-3"><button type="button" disabled={session.isPending}
        onClick={() => { setSignup(value => !value); session.reset(); setInvitation('') }} className="text-indigo-400 underline">
        {signup ? 'Use an existing account' : 'Use a task invitation'}</button>
        <Link to="/company/today" className="block text-gray-400 underline">Return to company workspace</Link></div>
    </section>
  </main>
}
