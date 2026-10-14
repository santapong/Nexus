import type { CompanyBudget } from '@/types/company'
import { money, StateLabel } from './CompanyStatus'

export function CompanyBudgetPanel({ budget }: { budget: CompanyBudget }) {
  const day = budget.daily
  return <section aria-label="Company budget" className="space-y-4">
    <div className="flex flex-wrap gap-2 justify-between items-center">
      <h2 className="text-base font-semibold text-white">Today’s allowance</h2>
      <span className="text-xs text-gray-400">{day.day} · Bangkok</span>
    </div>
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {[['Daily cap', day.cap_usd], ['Known spent today', day.spent_usd], ['Held today', day.held_usd],
        ['Available today', day.available_usd]].map(([label, value]) => <div key={label}
          className="rounded-lg bg-gray-900 border border-gray-800 p-4">
          <p className="text-xs text-gray-400">{label}</p><p className="text-xl text-white font-semibold mt-2">{money(value)}</p></div>)}
    </div>
    <div className="grid sm:grid-cols-2 gap-4 rounded-lg border border-gray-800 p-4 bg-gray-900">
      <div><p className="text-xs text-gray-400">Permanent plan allocations</p>
        <p className="font-semibold text-white mt-1">{money(budget.root_lifetime_allocated_usd)}</p>
        <p className="text-xs text-gray-400 mt-2">Inherited work allowances persist across days and retries.</p></div>
      <div><p className="text-xs text-gray-400">All recorded action costs</p>
        <p className="font-semibold text-white mt-1">{money(budget.actual_total_usd)}</p>
        {budget.billing_unconfirmed && <StateLabel warn>Billing unconfirmed</StateLabel>}
        <p className="text-xs text-gray-400 mt-2">Known portion {money(budget.known_spent_usd)} · Retained reservations {money(budget.reserved_any_day_usd)}</p></div>
    </div>
  </section>
}
