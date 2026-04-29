import { ShieldCheck, Check, X } from 'lucide-react'
import { useApprovals, useResolveApproval } from '../../hooks/useApprovals'
import { Button } from '../ui/button'

export function ApprovalPanel() {
  const { data: approvals = [] } = useApprovals()
  const resolveMutation = useResolveApproval()

  const pending = approvals.filter((a) => a.status === 'pending')

  if (pending.length === 0) return null

  return (
    <section
      className="bg-amber-950/40 border border-amber-800/60 rounded-lg p-5"
      aria-labelledby="approvals-heading"
    >
      <h2
        id="approvals-heading"
        className="flex items-center gap-2 text-lg font-semibold mb-3 text-amber-200"
      >
        <ShieldCheck size={18} aria-hidden="true" />
        Approvals needed
        <span className="text-sm font-normal text-amber-300/80">({pending.length})</span>
      </h2>
      <ul className="space-y-3" role="list">
        {pending.map((a) => (
          <li key={a.id} className="bg-gray-900 rounded-md p-4 space-y-2 border border-gray-800">
            <p className="text-sm text-gray-200">
              <span className="font-mono px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 text-xs">
                {a.tool_name}
              </span>
              <span className="ml-2">{a.action_description}</span>
            </p>
            <p className="text-xs text-gray-500 font-mono">task {a.task_id}</p>
            <div className="flex gap-2 mt-2">
              <Button
                variant="success"
                size="sm"
                onClick={() => resolveMutation.mutate({ id: a.id, approved: true })}
                disabled={resolveMutation.isPending}
                aria-label={`Approve ${a.tool_name} for task ${a.task_id}`}
              >
                <Check size={14} aria-hidden="true" />
                Approve
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => resolveMutation.mutate({ id: a.id, approved: false })}
                disabled={resolveMutation.isPending}
                aria-label={`Reject ${a.tool_name} for task ${a.task_id}`}
              >
                <X size={14} aria-hidden="true" />
                Reject
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
