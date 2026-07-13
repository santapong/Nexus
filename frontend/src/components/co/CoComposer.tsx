import { useState } from 'react'
import { Mic, Paperclip, SendHorizonal } from 'lucide-react'
import { useCreateTask } from '@/hooks/useTasks'
import { cn } from '@/lib/utils'

/**
 * The composer bar under the Co node: text now; the mic and file-drop
 * affordances are rendered here and wired up in the multimodal chunk (C5).
 */
export function CoComposer() {
  const [text, setText] = useState('')
  const createTask = useCreateTask()

  const submit = () => {
    const instruction = text.trim()
    if (!instruction || createTask.isPending) return
    createTask.mutate(instruction, {
      onSuccess: () => setText(''),
    })
  }

  return (
    <div className="pointer-events-auto w-full max-w-2xl rounded-2xl border border-gray-800 bg-gray-900/95 p-3 shadow-2xl backdrop-blur">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
        rows={2}
        placeholder="Ask Co anything — it will brief the team…"
        className="w-full resize-none bg-transparent text-sm text-gray-100 placeholder:text-gray-500 focus:outline-none"
      />
      <div className="mt-2 flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            title="Attach files (coming in the next update)"
            disabled
            className="rounded-lg p-2 text-gray-500 opacity-60"
          >
            <Paperclip size={16} />
          </button>
          <button
            type="button"
            title="Speak to Co (coming in the next update)"
            disabled
            className="rounded-lg p-2 text-gray-500 opacity-60"
          >
            <Mic size={16} />
          </button>
        </div>
        <button
          type="button"
          onClick={submit}
          disabled={!text.trim() || createTask.isPending}
          className={cn(
            'flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-1.5 text-sm font-medium text-white',
            'transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40',
          )}
        >
          <SendHorizonal size={14} />
          {createTask.isPending ? 'Sending…' : 'Send'}
        </button>
      </div>
    </div>
  )
}
