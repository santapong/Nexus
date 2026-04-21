import { useState } from 'react'
import { useSubmitTaskFeedback } from '../../hooks/useAnalytics'

type Props = {
  taskId: string
  onClose: () => void
}

export function TaskFeedbackModal({ taskId, onClose }: Props) {
  const [helpful, setHelpful] = useState<number>(0)
  const [safe, setSafe] = useState<number>(0)
  const [comment, setComment] = useState<string>('')
  const mutation = useSubmitTaskFeedback(taskId)

  const canSubmit = helpful >= 1 && safe >= 1 && !mutation.isPending

  function handleSubmit() {
    if (!canSubmit) return
    mutation.mutate(
      {
        helpful_score: helpful,
        safe_score: safe,
        comment: comment.trim() ? comment.trim() : null,
      },
      { onSuccess: onClose },
    )
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl border border-gray-700 bg-gray-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-gray-700 px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">🗣️</span>
            <h3 className="text-sm font-semibold text-white">Rate this task</h3>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 transition-colors hover:text-white"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="space-y-5 p-4">
          <ScoreRow
            label="Helpful"
            hint="Was the output useful?"
            value={helpful}
            onChange={setHelpful}
          />
          <ScoreRow
            label="Safe"
            hint="Was it in-scope, non-toxic, and on-topic?"
            value={safe}
            onChange={setSafe}
          />

          <div>
            <label className="mb-1 block text-xs uppercase tracking-wider text-gray-500">
              Comment (optional)
            </label>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              maxLength={2000}
              rows={3}
              placeholder="Anything you'd change about this output?"
              className="w-full resize-none rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
            />
            <div className="mt-1 text-right text-[10px] text-gray-600">
              {comment.length}/2000
            </div>
          </div>

          {mutation.isError && (
            <div className="rounded-lg border border-red-800/50 bg-red-950/40 px-3 py-2 text-xs text-red-300">
              Failed to submit feedback. Try again.
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-gray-700 bg-gray-800/40 px-4 py-3">
          <button
            onClick={onClose}
            className="rounded-lg px-3 py-1.5 text-xs text-gray-400 transition-colors hover:text-white"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition-all hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-gray-700 disabled:text-gray-500"
          >
            {mutation.isPending ? 'Submitting…' : 'Submit feedback'}
          </button>
        </div>
      </div>
    </div>
  )
}

function ScoreRow({
  label,
  hint,
  value,
  onChange,
}: {
  label: string
  hint: string
  value: number
  onChange: (v: number) => void
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <label className="text-xs uppercase tracking-wider text-gray-400">{label}</label>
        <span className="text-[11px] text-gray-500">{hint}</span>
      </div>
      <div className="flex items-center gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => onChange(n)}
            className={`h-8 w-8 rounded-md border text-sm transition-all ${
              n <= value
                ? 'border-indigo-500 bg-indigo-600 text-white'
                : 'border-gray-700 bg-gray-800 text-gray-400 hover:border-gray-600 hover:text-gray-200'
            }`}
            aria-label={`${label} score ${n}`}
          >
            {n}
          </button>
        ))}
        <span className="ml-2 text-xs text-gray-500">
          {value === 0 ? 'unrated' : `${value}/5`}
        </span>
      </div>
    </div>
  )
}
