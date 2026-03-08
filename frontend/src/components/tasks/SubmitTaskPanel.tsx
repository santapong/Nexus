import { useState } from 'react'
import { useCreateTask } from '../../hooks/useTasks'

export function SubmitTaskPanel() {
  const [instruction, setInstruction] = useState('')
  const mutation = useCreateTask()

  const handleSubmit = () => {
    mutation.mutate(instruction, {
      onSuccess: () => setInstruction(''),
    })
  }

  return (
    <section className="bg-gray-900 rounded-lg p-5">
      <h2 className="text-lg font-semibold mb-3 text-white">Submit Task</h2>
      <textarea
        className="w-full bg-gray-800 text-gray-100 rounded p-3 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-blue-500"
        rows={4}
        placeholder="Describe the task for the Engineer agent..."
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
      />
      <div className="flex items-center gap-3 mt-3">
        <button
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          onClick={handleSubmit}
          disabled={!instruction.trim() || mutation.isPending}
        >
          {mutation.isPending ? 'Submitting...' : 'Submit'}
        </button>
        {mutation.isError && <span className="text-red-400 text-sm">Failed to submit task</span>}
        {mutation.isSuccess && <span className="text-green-400 text-sm">Task queued!</span>}
      </div>
    </section>
  )
}
