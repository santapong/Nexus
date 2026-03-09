import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../api/client';

interface PromptData {
  id: string;
  agent_role: string;
  version: number;
  content: string;
  benchmark_score: number | null;
  is_active: boolean;
  authored_by: string;
  notes: string | null;
  created_at: string;
  approved_at: string | null;
}

interface PromptDiff {
  current: PromptData | null;
  proposed: PromptData;
  diff_lines: string[];
}

export function usePrompts(role?: string) {
  return useQuery<PromptData[]>({
    queryKey: ['prompts', role],
    queryFn: () => {
      const params = new URLSearchParams();
      if (role) params.set('role', role);
      return apiFetch<PromptData[]>(`/api/prompts?${params.toString()}`);
    },
  });
}

export function usePromptDiff(promptId: string | null) {
  return useQuery<PromptDiff>({
    queryKey: ['prompt-diff', promptId],
    queryFn: () => apiFetch<PromptDiff>(`/api/prompts/${promptId}/diff`),
    enabled: !!promptId,
  });
}

export function useActivatePrompt() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (promptId: string) =>
      apiFetch<{ status: string }>(`/api/prompts/${promptId}/activate`, {
        method: 'POST',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompts'] });
    },
  });
}

export function useTriggerImprovement() {
  return useMutation({
    mutationFn: (targetRole: string) =>
      apiFetch<{ status: string; task_id: string }>('/api/prompts/improve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_role: targetRole }),
      }),
  });
}
