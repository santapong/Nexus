import { useTasks } from '../../hooks/useTasks'
import { TaskRow } from './TaskRow'

export function TaskListPanel() {
  const { data: tasks = [], isLoading } = useTasks()

  return (
    <section className="bg-gray-900 rounded-lg p-5">
      <h2 className="text-lg font-semibold mb-3 text-white">
        Tasks
        <span className="ml-2 text-sm text-gray-500 font-normal">({tasks.length})</span>
      </h2>
      {isLoading && <p className="text-gray-400 text-sm">Loading...</p>}
      {!isLoading && tasks.length === 0 && (
        <p className="text-gray-500 text-sm">No tasks yet. Submit one above.</p>
      )}
      <div className="space-y-2">
        {tasks.map((t) => (
          <TaskRow key={t.id} task={t} />
        ))}
      </div>
    </section>
  )
}
