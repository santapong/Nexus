import { useApprovals, useResolveApproval } from '../../hooks/useApprovals'

export function ApprovalPanel() {
  const { data: approvals = [] } = useApprovals()
  const resolveMutation = useResolveApproval()

  const pending = approvals.filter((a) => a.status === 'pending')

  if (pending.length === 0) return null

  return (
    <section className="bg-yellow-950 border border-yellow-800 rounded-lg p-5">
      <h2 className="text-lg font-semibold mb-3 text-yellow-300">
        Approvals Needed ({pending.length})
      </h2>
      <div className="space-y-3">
        {pending.map((a) => (
          <div key={a.id} className="bg-gray-900 rounded p-4 space-y-2">
            <p className="text-sm text-gray-200">
              <span className="font-medium text-yellow-400">{a.tool_name}</span>
              {' \u2014 '}
              {a.action_description}
            </p>
            <p className="text-xs text-gray-500">Task: {a.task_id}</p>
            <div className="flex gap-2 mt-2">
              <button
                className="px-3 py-1 bg-green-700 hover:bg-green-600 text-white rounded text-sm disabled:opacity-50"
                onClick={() => resolveMutation.mutate({ id: a.id, approved: true })}
                disabled={resolveMutation.isPending}
              >
                Approve
              </button>
              <button
                className="px-3 py-1 bg-red-700 hover:bg-red-600 text-white rounded text-sm disabled:opacity-50"
                onClick={() => resolveMutation.mutate({ id: a.id, approved: false })}
                disabled={resolveMutation.isPending}
              >
                Reject
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
