import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../api/client';

interface TaskTraceSubtask {
  id: string;
  trace_id: string;
  parent_task_id: string | null;
  instruction: string;
  status: string;
  source: string;
  tokens_used: number;
  output: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

interface TaskTrace {
  parent: TaskTraceSubtask;
  subtasks: TaskTraceSubtask[];
  total_subtasks: number;
  completed_subtasks: number;
}

export function useTaskTrace(taskId: string | null) {
  return useQuery<TaskTrace>({
    queryKey: ['task-trace', taskId],
    queryFn: () => apiFetch<TaskTrace>(`/api/tasks/${taskId}/trace`),
    enabled: !!taskId,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 5000;
      const parentDone = ['completed', 'failed', 'escalated'].includes(
        data.parent.status
      );
      return parentDone ? false : 5000;
    },
  });
}
