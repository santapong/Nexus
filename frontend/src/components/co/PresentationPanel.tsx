import { useEffect, useRef, useState } from 'react'
import { Volume2, VolumeX, X } from 'lucide-react'
import { useAgentEventStore } from '@/ws/agentEventStore'
import { useSpeechSynthesis } from '@/hooks/useSpeech'
import type { Presentation } from '@/types'

function isPresentation(value: unknown): value is Presentation {
  if (typeof value !== 'object' || value === null) return false
  const p = value as Record<string, unknown>
  return (
    (p.format === 'html' || p.format === 'markdown' || p.format === 'mermaid') &&
    typeof p.content === 'string' &&
    typeof p.speech_text === 'string'
  )
}

/**
 * Renders Co's presentation output (ADR-091) when a task_result arrives.
 * HTML (already sanitized server-side, twice) renders inside a fully
 * sandboxed iframe — no scripts, no same-origin. Markdown/mermaid render
 * as escaped text. speech_text is auto-spoken once per task via the
 * browser TTS backend.
 */
export function PresentationPanel() {
  const lastTaskResult = useAgentEventStore((s) => s.lastTaskResult)
  const [dismissedTaskId, setDismissedTaskId] = useState<string | null>(null)
  const spokenTaskRef = useRef<string | null>(null)
  const tts = useSpeechSynthesis()

  const presentation =
    lastTaskResult && isPresentation(lastTaskResult.output?.presentation)
      ? lastTaskResult.output?.presentation
      : null
  const visible =
    presentation !== null && lastTaskResult !== null && lastTaskResult.task_id !== dismissedTaskId

  useEffect(() => {
    if (!visible || !presentation || !lastTaskResult) return
    if (spokenTaskRef.current === lastTaskResult.task_id) return
    spokenTaskRef.current = lastTaskResult.task_id
    if (tts.supported && presentation.speech_text) {
      tts.speak(presentation.speech_text)
    }
  }, [visible, presentation, lastTaskResult, tts])

  if (!visible || !presentation || !lastTaskResult) return null

  const iframeDoc = `<!doctype html><html><head><style>
    body{font-family:ui-sans-serif,system-ui,sans-serif;color:#e5e7eb;background:#0b1120;margin:0;padding:20px;font-size:14px;line-height:1.6}
    h1,h2,h3{color:#eef2ff} a{color:#818cf8}
    table{border-collapse:collapse;width:100%} th,td{border:1px solid #334155;padding:6px 10px;text-align:left}
    code,pre{background:#111827;border-radius:6px;padding:2px 6px} pre{padding:12px;overflow-x:auto}
    blockquote{border-left:3px solid #4f46e5;margin-left:0;padding-left:12px;color:#9ca3af}
  </style></head><body>${presentation.content}</body></html>`

  return (
    <div className="pointer-events-auto absolute inset-y-6 right-6 z-10 flex w-[min(560px,45vw)] flex-col overflow-hidden rounded-2xl border border-gray-700 bg-gray-950 shadow-2xl">
      <header className="flex items-center justify-between border-b border-gray-800 bg-gray-900 px-4 py-2.5">
        <h2 className="text-sm font-semibold text-gray-100">Co's result</h2>
        <div className="flex items-center gap-1">
          {tts.supported && (
            <>
              <button
                type="button"
                title="Read aloud"
                onClick={() => tts.speak(presentation.speech_text)}
                className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-800 hover:text-gray-200"
              >
                <Volume2 size={15} />
              </button>
              <button
                type="button"
                title="Stop speaking"
                onClick={() => tts.stop()}
                className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-800 hover:text-gray-200"
              >
                <VolumeX size={15} />
              </button>
            </>
          )}
          <button
            type="button"
            title="Close"
            onClick={() => {
              tts.stop()
              setDismissedTaskId(lastTaskResult.task_id)
            }}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-800 hover:text-gray-200"
          >
            <X size={15} />
          </button>
        </div>
      </header>
      {presentation.format === 'html' ? (
        <iframe
          title="Co presentation"
          sandbox=""
          srcDoc={iframeDoc}
          className="h-full w-full flex-1 border-0 bg-[#0b1120]"
        />
      ) : (
        <pre className="flex-1 overflow-auto whitespace-pre-wrap p-4 text-sm leading-relaxed text-gray-200">
          {presentation.content}
        </pre>
      )}
    </div>
  )
}
