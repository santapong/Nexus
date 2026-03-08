const STATUS_COLORS: Record<string, string> = {
  queued: 'bg-gray-600 text-gray-100',
  running: 'bg-blue-600 text-blue-100',
  completed: 'bg-green-700 text-green-100',
  failed: 'bg-red-700 text-red-100',
  paused: 'bg-yellow-700 text-yellow-100',
  escalated: 'bg-orange-700 text-orange-100',
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[status] ?? 'bg-gray-700 text-gray-200'}`}
    >
      {status}
    </span>
  )
}
