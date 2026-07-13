import { useCallback, useRef, useState } from 'react'
import { FileText, Loader2, Mic, MicOff, Paperclip, SendHorizonal, X } from 'lucide-react'
import { useCreateTask } from '@/hooks/useTasks'
import { useUploadFile } from '@/hooks/useUploads'
import { useSpeechRecognition } from '@/hooks/useSpeech'
import type { AttachmentRef } from '@/types'
import { cn } from '@/lib/utils'

interface PendingUpload {
  key: string
  filename: string
  status: 'uploading' | 'done' | 'failed'
  ref?: AttachmentRef
}

/**
 * The Co composer: text, browser-mic dictation (ADR-088 browser backend),
 * and file attachments via drag-drop or the paperclip (ADR-089).
 */
export function CoComposer() {
  const [text, setText] = useState('')
  const [interim, setInterim] = useState('')
  const [uploads, setUploads] = useState<PendingUpload[]>([])
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const createTask = useCreateTask()
  const uploadFile = useUploadFile()

  const handleTranscript = useCallback((transcript: string, isFinal: boolean) => {
    if (isFinal) {
      setText((prev) => (prev ? `${prev.trimEnd()} ${transcript.trim()}` : transcript.trim()))
      setInterim('')
    } else {
      setInterim(transcript)
    }
  }, [])

  const mic = useSpeechRecognition(handleTranscript)

  const addFiles = useCallback(
    (files: FileList | File[]) => {
      for (const file of Array.from(files)) {
        const key = `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
        setUploads((prev) => [...prev, { key, filename: file.name, status: 'uploading' }])
        uploadFile.mutate(file, {
          onSuccess: (ref) =>
            setUploads((prev) =>
              prev.map((u) => (u.key === key ? { ...u, status: 'done', ref } : u)),
            ),
          onError: () =>
            setUploads((prev) =>
              prev.map((u) => (u.key === key ? { ...u, status: 'failed' } : u)),
            ),
        })
      }
    },
    [uploadFile],
  )

  const submit = () => {
    const instruction = text.trim()
    const uploading = uploads.some((u) => u.status === 'uploading')
    if (!instruction || createTask.isPending || uploading) return
    const attachments = uploads
      .filter((u) => u.status === 'done' && u.ref)
      .map((u) => (u.ref as AttachmentRef).id)
    if (mic.listening) mic.stop()
    createTask.mutate(
      { instruction, attachments },
      {
        onSuccess: () => {
          setText('')
          setInterim('')
          setUploads([])
        },
      },
    )
  }

  const uploading = uploads.some((u) => u.status === 'uploading')

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        if (e.dataTransfer.files.length > 0) addFiles(e.dataTransfer.files)
      }}
      className={cn(
        'pointer-events-auto w-full max-w-2xl rounded-2xl border bg-gray-900/95 p-3 shadow-2xl backdrop-blur',
        dragOver ? 'border-indigo-400 ring-2 ring-indigo-500/40' : 'border-gray-800',
      )}
    >
      {uploads.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {uploads.map((u) => (
            <span
              key={u.key}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px]',
                u.status === 'done' && 'border-emerald-700 bg-emerald-950/60 text-emerald-300',
                u.status === 'uploading' && 'border-gray-700 bg-gray-800 text-gray-300',
                u.status === 'failed' && 'border-red-800 bg-red-950/60 text-red-300',
              )}
            >
              {u.status === 'uploading' ? (
                <Loader2 size={11} className="animate-spin" />
              ) : (
                <FileText size={11} />
              )}
              <span className="max-w-40 truncate">{u.filename}</span>
              {u.status === 'done' && u.ref && (
                <span className="text-emerald-500/80">{u.ref.parse_status}</span>
              )}
              {u.status === 'failed' && <span>failed</span>}
              <button
                type="button"
                onClick={() => setUploads((prev) => prev.filter((x) => x.key !== u.key))}
                className="opacity-70 hover:opacity-100"
              >
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
      )}

      <textarea
        value={interim ? `${text}${text ? ' ' : ''}${interim}` : text}
        onChange={(e) => {
          setText(e.target.value)
          setInterim('')
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
        rows={2}
        placeholder={
          mic.listening
            ? 'Listening… speak to Co'
            : 'Ask Co anything — drop files here, type, or use the mic…'
        }
        className="w-full resize-none bg-transparent text-sm text-gray-100 placeholder:text-gray-500 focus:outline-none"
      />
      <div className="mt-2 flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              if (e.target.files) addFiles(e.target.files)
              e.target.value = ''
            }}
          />
          <button
            type="button"
            title="Attach files"
            onClick={() => fileInputRef.current?.click()}
            className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-800 hover:text-gray-200"
          >
            <Paperclip size={16} />
          </button>
          <button
            type="button"
            title={
              mic.supported
                ? mic.listening
                  ? 'Stop listening'
                  : 'Speak to Co'
                : 'Voice input is not supported in this browser'
            }
            disabled={!mic.supported}
            onClick={() => (mic.listening ? mic.stop() : mic.start())}
            className={cn(
              'rounded-lg p-2 transition-colors',
              mic.listening
                ? 'bg-red-950 text-red-400 hover:bg-red-900'
                : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200',
              !mic.supported && 'cursor-not-allowed opacity-40',
            )}
          >
            {mic.listening ? <MicOff size={16} /> : <Mic size={16} />}
          </button>
        </div>
        <button
          type="button"
          onClick={submit}
          disabled={!text.trim() || createTask.isPending || uploading}
          className={cn(
            'flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-1.5 text-sm font-medium text-white',
            'transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40',
          )}
        >
          <SendHorizonal size={14} />
          {createTask.isPending ? 'Sending…' : uploading ? 'Uploading…' : 'Send'}
        </button>
      </div>
    </div>
  )
}
