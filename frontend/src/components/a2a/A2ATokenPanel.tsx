import { useState } from 'react'
import {
  useA2ATokens,
  useCreateA2AToken,
  useRevokeA2AToken,
  useRotateA2AToken,
} from '../../hooks/useA2ATokens'

export function A2ATokenPanel() {
  const { data: tokens, isLoading } = useA2ATokens()
  const createToken = useCreateA2AToken()
  const revokeToken = useRevokeA2AToken()
  const rotateToken = useRotateA2AToken()

  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [skills, setSkills] = useState('*')
  const [newToken, setNewToken] = useState<string | null>(null)

  const handleCreate = () => {
    const skillList = skills.split(',').map((s) => s.trim()).filter(Boolean)
    createToken.mutate(
      { name, skills: skillList },
      {
        onSuccess: (data) => {
          setNewToken(data.token)
          setName('')
          setSkills('*')
          setShowCreate(false)
        },
      }
    )
  }

  const handleRotate = (id: string) => {
    rotateToken.mutate(id, {
      onSuccess: (data) => setNewToken(data.token),
    })
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <span className="text-2xl">🔑</span> A2A Tokens
        </h2>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="px-3 py-1 text-xs bg-indigo-600 text-white rounded-md hover:bg-indigo-500 transition-all"
        >
          {showCreate ? 'Cancel' : 'New Token'}
        </button>
      </div>

      {/* New token alert */}
      {newToken && (
        <div className="bg-green-950/30 border border-green-800/50 rounded-xl p-4">
          <div className="text-xs text-green-400 font-semibold mb-1">
            Token created — copy it now (shown only once):
          </div>
          <div className="flex items-center gap-2">
            <code className="text-green-300 bg-green-950/50 px-3 py-2 rounded font-mono text-xs flex-1 break-all">
              {newToken}
            </code>
            <button
              onClick={() => {
                navigator.clipboard.writeText(newToken)
                setNewToken(null)
              }}
              className="px-2 py-2 text-xs bg-green-800/50 text-green-300 rounded hover:bg-green-700/50 transition-all whitespace-nowrap"
            >
              Copy & Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Create form */}
      {showCreate && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3">
          <div>
            <label className="text-xs text-gray-400 block mb-1">Token Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., partner-agent-prod"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">
              Allowed Skills (comma-separated, * for all)
            </label>
            <input
              value={skills}
              onChange={(e) => setSkills(e.target.value)}
              placeholder="research, code, write"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
            />
          </div>
          <button
            onClick={handleCreate}
            disabled={!name.trim() || createToken.isPending}
            className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 disabled:opacity-50 transition-all"
          >
            {createToken.isPending ? 'Creating...' : 'Create Token'}
          </button>
        </div>
      )}

      {/* Token list */}
      {isLoading ? (
        <div className="text-gray-500 text-sm animate-pulse">Loading tokens...</div>
      ) : tokens && tokens.length > 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-xs uppercase tracking-wider">
                <th className="text-left px-4 py-2">Name</th>
                <th className="text-left px-4 py-2">Hash</th>
                <th className="text-left px-4 py-2">Skills</th>
                <th className="text-right px-4 py-2">RPM</th>
                <th className="text-left px-4 py-2">Status</th>
                <th className="text-right px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {tokens.map((token) => (
                <tr key={token.id} className="border-t border-gray-800 hover:bg-gray-800/50 transition-colors">
                  <td className="px-4 py-3 text-white font-medium">{token.name}</td>
                  <td className="px-4 py-3 text-gray-400 font-mono text-xs">
                    {token.token_hash_prefix}...
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1 flex-wrap">
                      {token.allowed_skills.map((s) => (
                        <span key={s} className="px-1.5 py-0.5 bg-gray-800 text-gray-300 rounded text-xs">
                          {s}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="text-right px-4 py-3 text-gray-300">{token.rate_limit_rpm}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      token.is_revoked
                        ? 'bg-red-950/50 text-red-400'
                        : 'bg-green-950/50 text-green-400'
                    }`}>
                      {token.is_revoked ? 'Revoked' : 'Active'}
                    </span>
                  </td>
                  <td className="text-right px-4 py-3">
                    {!token.is_revoked && (
                      <div className="flex gap-1 justify-end">
                        <button
                          onClick={() => handleRotate(token.id)}
                          disabled={rotateToken.isPending}
                          className="px-2 py-1 text-xs bg-gray-700 text-gray-300 rounded hover:bg-gray-600 disabled:opacity-50 transition-all"
                        >
                          Rotate
                        </button>
                        <button
                          onClick={() => revokeToken.mutate(token.id)}
                          disabled={revokeToken.isPending}
                          className="px-2 py-1 text-xs bg-red-900/50 text-red-400 rounded hover:bg-red-800/50 disabled:opacity-50 transition-all"
                        >
                          Revoke
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-gray-500 text-sm">
          No A2A tokens issued. Create one to allow external agents to call NEXUS.
        </div>
      )}
    </div>
  )
}
