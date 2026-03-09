import { useState } from 'react';
import {
  usePrompts,
  usePromptDiff,
  useActivatePrompt,
  useTriggerImprovement,
} from '../../hooks/usePrompts';

const ROLES = ['ceo', 'engineer', 'analyst', 'writer', 'qa', 'prompt_creator'];

export function PromptDiffView() {
  const [selectedRole, setSelectedRole] = useState<string>('');
  const [selectedPromptId, setSelectedPromptId] = useState<string | null>(null);

  const { data: prompts, isLoading } = usePrompts(selectedRole || undefined);
  const { data: diff } = usePromptDiff(selectedPromptId);
  const activateMutation = useActivatePrompt();
  const improveMutation = useTriggerImprovement();

  const proposedPrompts = prompts?.filter((p) => !p.is_active) ?? [];
  const activePrompts = prompts?.filter((p) => p.is_active) ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-white">Prompt Management</h2>
        <div className="flex items-center gap-3">
          <select
            value={selectedRole}
            onChange={(e) => {
              setSelectedRole(e.target.value);
              setSelectedPromptId(null);
            }}
            className="bg-gray-800 text-gray-200 border border-gray-600 rounded px-3 py-1.5 text-sm"
          >
            <option value="">All Roles</option>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r.toUpperCase()}
              </option>
            ))}
          </select>
          {selectedRole && (
            <button
              onClick={() => improveMutation.mutate(selectedRole)}
              disabled={improveMutation.isPending}
              className="px-3 py-1.5 bg-purple-600 hover:bg-purple-500 disabled:bg-gray-600 text-white text-sm rounded transition-colors"
            >
              {improveMutation.isPending ? 'Triggering...' : '⚡ Trigger Improvement'}
            </button>
          )}
        </div>
      </div>

      {isLoading && (
        <div className="text-gray-400 animate-pulse">Loading prompts...</div>
      )}

      {/* Active prompts */}
      {activePrompts.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-2">
            Active Prompts
          </h3>
          <div className="space-y-2">
            {activePrompts.map((p) => (
              <div
                key={p.id}
                className="bg-gray-800 border border-green-800 rounded-lg p-4"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 bg-green-700 text-green-100 text-xs rounded">
                      ACTIVE
                    </span>
                    <span className="text-sm font-medium text-white">
                      {p.agent_role.toUpperCase()} v{p.version}
                    </span>
                  </div>
                  <div className="text-xs text-gray-500">
                    {p.benchmark_score !== null && `Score: ${(p.benchmark_score * 100).toFixed(0)}%`}
                    {' · '}By: {p.authored_by}
                  </div>
                </div>
                <pre className="mt-2 text-xs text-gray-400 max-h-32 overflow-auto whitespace-pre-wrap">
                  {p.content.slice(0, 300)}
                  {p.content.length > 300 && '...'}
                </pre>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Proposed prompts */}
      {proposedPrompts.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-2">
            Proposed Improvements
          </h3>
          <div className="space-y-2">
            {proposedPrompts.map((p) => (
              <div
                key={p.id}
                className={`bg-gray-800 border rounded-lg p-4 cursor-pointer transition-colors ${
                  selectedPromptId === p.id
                    ? 'border-indigo-500'
                    : 'border-gray-700 hover:border-gray-500'
                }`}
                onClick={() => setSelectedPromptId(p.id)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 bg-yellow-700 text-yellow-100 text-xs rounded">
                      PROPOSED
                    </span>
                    <span className="text-sm font-medium text-white">
                      {p.agent_role.toUpperCase()} v{p.version}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-gray-500">
                      {p.benchmark_score !== null && `Score: ${(p.benchmark_score * 100).toFixed(0)}%`}
                    </span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        activateMutation.mutate(p.id);
                      }}
                      disabled={activateMutation.isPending}
                      className="px-2 py-1 bg-green-700 hover:bg-green-600 disabled:bg-gray-600 text-white text-xs rounded transition-colors"
                    >
                      ✓ Approve
                    </button>
                  </div>
                </div>
                {p.notes && (
                  <p className="mt-1 text-xs text-gray-500">{p.notes}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Diff view */}
      {diff && (
        <div className="bg-gray-800 border border-gray-700 rounded-lg overflow-hidden">
          <div className="p-3 border-b border-gray-700">
            <h3 className="text-sm font-medium text-white">
              Diff: {diff.proposed.agent_role.toUpperCase()} v
              {diff.current?.version ?? '?'} →  v{diff.proposed.version}
            </h3>
            <div className="flex items-center gap-4 mt-1 text-xs text-gray-500">
              {diff.current && (
                <span>
                  Current score: {diff.current.benchmark_score !== null
                    ? `${(diff.current.benchmark_score * 100).toFixed(0)}%`
                    : 'N/A'}
                </span>
              )}
              <span>
                Proposed score: {diff.proposed.benchmark_score !== null
                  ? `${(diff.proposed.benchmark_score * 100).toFixed(0)}%`
                  : 'N/A'}
              </span>
            </div>
          </div>
          <div className="p-3 font-mono text-xs max-h-96 overflow-auto">
            {diff.diff_lines.map((line, i) => (
              <div
                key={i}
                className={
                  line.startsWith('+')
                    ? 'text-green-400 bg-green-900/20'
                    : line.startsWith('-')
                    ? 'text-red-400 bg-red-900/20'
                    : 'text-gray-400'
                }
              >
                {line}
              </div>
            ))}
            {diff.diff_lines.length === 0 && (
              <div className="text-gray-500">No differences found</div>
            )}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && prompts?.length === 0 && (
        <div className="text-center py-8 text-gray-500">
          No prompts found{selectedRole ? ` for ${selectedRole}` : ''}.
        </div>
      )}
    </div>
  );
}
