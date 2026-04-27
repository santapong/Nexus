import { useState, useMemo } from 'react'
import { useTasks } from '../../hooks/useTasks'
import { TaskRow } from './TaskRow'
import { Input } from '../ui/input'
import { Select } from '../ui/select'
import { Button } from '../ui/button'
import { Skeleton } from '../ui/skeleton'
import { EmptyState } from '../ui/empty-state'
import { Inbox, Search, X } from 'lucide-react'

const STATUS_OPTIONS = ['all', 'queued', 'running', 'completed', 'failed', 'paused', 'escalated'] as const

export function TaskListPanel() {
  const { data: tasks = [], isLoading } = useTasks()
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [sortOrder, setSortOrder] = useState<'newest' | 'oldest'>('newest')

  const filtered = useMemo(() => {
    let result = [...tasks]

    if (search.trim()) {
      const q = search.toLowerCase()
      result = result.filter((t) => t.instruction.toLowerCase().includes(q))
    }

    if (statusFilter !== 'all') {
      result = result.filter((t) => t.status === statusFilter)
    }

    result.sort((a, b) => {
      const dateA = new Date(a.created_at).getTime()
      const dateB = new Date(b.created_at).getTime()
      return sortOrder === 'newest' ? dateB - dateA : dateA - dateB
    })

    return result
  }, [tasks, search, statusFilter, sortOrder])

  const hasFilters = search.trim() !== '' || statusFilter !== 'all'

  return (
    <section className="bg-gray-900 rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white">
          Tasks
          <span className="ml-2 text-sm text-gray-500 font-normal">
            ({filtered.length}{hasFilters ? ` of ${tasks.length}` : ''})
          </span>
        </h2>
        <div className="flex items-center gap-2">
          <Select
            value={sortOrder}
            onChange={(e) => setSortOrder(e.target.value as 'newest' | 'oldest')}
            className="w-32"
          >
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
          </Select>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <Input
            placeholder="Search tasks..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="w-36"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s === 'all' ? 'All statuses' : s.charAt(0).toUpperCase() + s.slice(1)}
            </option>
          ))}
        </Select>
        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSearch('')
              setStatusFilter('all')
            }}
          >
            <X size={14} />
            Clear
          </Button>
        )}
      </div>

      {isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      )}
      {!isLoading && filtered.length === 0 && (
        <EmptyState
          icon={<Inbox size={28} strokeWidth={1.5} />}
          title={hasFilters ? 'No tasks match your filters' : 'No tasks yet'}
          description={
            hasFilters
              ? 'Try clearing filters or broadening your search.'
              : 'Use the “Submit task” form above to dispatch your first instruction to the agents.'
          }
          action={
            hasFilters ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setSearch('')
                  setStatusFilter('all')
                }}
              >
                <X size={14} />
                Clear filters
              </Button>
            ) : undefined
          }
        />
      )}
      <div className="space-y-2">
        {filtered.map((t) => (
          <TaskRow key={t.id} task={t} />
        ))}
      </div>
    </section>
  )
}
