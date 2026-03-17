import { useState } from 'react'
import { useBillingSummary, useBillingRecords, useInvoice } from '../../hooks/useBilling'

const PERIODS = [
  { label: '7 Days', value: '7d' },
  { label: '30 Days', value: '30d' },
  { label: '90 Days', value: '90d' },
]

export function BillingPanel() {
  const [period, setPeriod] = useState('30d')
  const [showInvoice, setShowInvoice] = useState(false)

  const { data: summary, isLoading: summaryLoading } = useBillingSummary(period)
  const { data: records, isLoading: recordsLoading } = useBillingRecords()
  const { data: invoice, refetch: fetchInvoice, isFetching: invoiceFetching } = useInvoice(period)

  const handleGenerateInvoice = () => {
    fetchInvoice()
    setShowInvoice(true)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <span className="text-2xl">💰</span> Billing
        </h2>
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              className={`px-3 py-1 text-xs rounded-md transition-all ${
                period === p.value
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Summary cards */}
      {summaryLoading ? (
        <div className="text-gray-500 text-sm animate-pulse">Loading summary...</div>
      ) : summary ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">
              Total Cost
            </div>
            <div className="text-2xl font-bold text-white">
              ${summary.total_cost_usd.toFixed(2)}
            </div>
            <div className="text-xs text-gray-500 mt-1">
              {summary.period_start} - {summary.period_end}
            </div>
          </div>
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">
              Tasks Billed
            </div>
            <div className="text-2xl font-bold text-white">
              {summary.total_tasks_billed}
            </div>
            <div className="text-xs text-gray-500 mt-1">
              Avg: $
              {summary.total_tasks_billed > 0
                ? (summary.total_cost_usd / summary.total_tasks_billed).toFixed(3)
                : '0.000'}
              /task
            </div>
          </div>
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">
              Cost Breakdown
            </div>
            <div className="space-y-1 mt-1">
              {Object.entries(summary.by_type).map(([type, cost]) => (
                <div key={type} className="flex justify-between text-sm">
                  <span className="text-gray-400">{type}</span>
                  <span className="text-white font-medium">${cost.toFixed(2)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : null}

      {/* Generate invoice button */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleGenerateInvoice}
          disabled={invoiceFetching}
          className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 disabled:opacity-50 transition-all"
        >
          {invoiceFetching ? 'Generating...' : 'Generate Invoice'}
        </button>
      </div>

      {/* Invoice view */}
      {showInvoice && invoice && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-white font-semibold text-sm">Invoice</h3>
            <button
              onClick={() => setShowInvoice(false)}
              className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
            >
              Close
            </button>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs text-gray-400">
            <div>Workspace: {invoice.workspace_id}</div>
            <div>Generated: {invoice.generated_at}</div>
            <div>Period: {invoice.period_start} - {invoice.period_end}</div>
            <div className="text-white font-semibold">
              Total: ${invoice.total_amount_usd.toFixed(2)}
            </div>
          </div>
          {invoice.line_items.length > 0 && (
            <div className="bg-gray-950 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 text-xs uppercase tracking-wider">
                    <th className="text-left px-3 py-2">Description</th>
                    <th className="text-left px-3 py-2">Type</th>
                    <th className="text-right px-3 py-2">Amount</th>
                    <th className="text-left px-3 py-2">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {invoice.line_items.map((item) => (
                    <tr
                      key={item.id}
                      className="border-t border-gray-800 hover:bg-gray-800/50 transition-colors"
                    >
                      <td className="px-3 py-2 text-gray-300 text-xs">
                        {item.description}
                      </td>
                      <td className="px-3 py-2">
                        <span className="px-1.5 py-0.5 bg-gray-800 text-gray-300 rounded text-xs">
                          {item.billing_type}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right text-white text-xs font-medium">
                        ${item.amount_usd.toFixed(3)}
                      </td>
                      <td className="px-3 py-2 text-gray-500 text-xs">
                        {item.created_at}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Recent billing records */}
      <div>
        <h3 className="text-sm font-semibold text-gray-400 mb-2">Recent Billing Records</h3>
        {recordsLoading ? (
          <div className="text-gray-500 text-sm animate-pulse">Loading records...</div>
        ) : records && records.length > 0 ? (
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs uppercase tracking-wider">
                  <th className="text-left px-4 py-2">Description</th>
                  <th className="text-left px-4 py-2">Type</th>
                  <th className="text-right px-4 py-2">Amount</th>
                  <th className="text-left px-4 py-2">Date</th>
                </tr>
              </thead>
              <tbody>
                {records.slice(0, 10).map((record) => (
                  <tr
                    key={record.id}
                    className="border-t border-gray-800 hover:bg-gray-800/50 transition-colors"
                  >
                    <td className="px-4 py-3 text-gray-300 text-xs">
                      {record.description}
                    </td>
                    <td className="px-4 py-3">
                      <span className="px-1.5 py-0.5 bg-gray-800 text-gray-300 rounded text-xs">
                        {record.billing_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-white text-xs font-medium">
                      ${record.amount_usd.toFixed(3)}
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {record.created_at}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-gray-500 text-sm">No billing records yet.</div>
        )}
      </div>
    </div>
  )
}
