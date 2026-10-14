import { Button } from '@/components/ui/button'

export function CompanyQueryState({ pending, error, refresh }: {
  pending: boolean; error: Error | null; refresh?: () => void
}) {
  if (pending) return <p role="status" className="text-gray-400 py-6">Loading current company records…</p>
  if (!error) return null
  return <div role="alert" className="border border-red-800/50 rounded-lg bg-gray-900 p-5 space-y-3">
    <p className="font-medium text-white">Records are unavailable</p><p className="text-sm text-gray-400">{error.message}</p>
    {refresh && <Button variant="outline" onClick={refresh}>Refresh records</Button>}
  </div>
}

export function StateLabel({ children, warn = false }: { children: React.ReactNode; warn?: boolean }) {
  return <span className={`inline-flex rounded border px-2 py-0.5 text-xs ${warn
    ? 'border-amber-700 text-amber-500' : 'border-gray-700 text-gray-300'}`}>{children}</span>
}

export function money(value: string | number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return 'Unconfirmed'
  const amount = Number(value)
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD',
    minimumFractionDigits: 2, maximumFractionDigits: 6 }).format(amount)
}

export function instant(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString('en-GB', { timeZone: 'Asia/Bangkok',
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) + ' ICT' : 'Not scheduled'
}
