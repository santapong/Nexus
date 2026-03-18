import { useState } from 'react'
import { useLogin, useRegister } from '../../hooks/useAuth'

export function LoginPanel() {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const login = useLogin()
  const register = useRegister()

  const handleSubmit = () => {
    setError(null)
    setSuccess(null)

    if (!email.trim() || !password.trim()) {
      setError('Email and password are required.')
      return
    }

    if (mode === 'register') {
      if (!displayName.trim()) {
        setError('Display name is required for registration.')
        return
      }
      register.mutate(
        { email, password, displayName },
        {
          onSuccess: (data) => {
            localStorage.setItem('nexus_token', data.access_token)
            setSuccess(`Registered successfully. Workspace ID: ${data.workspace_id}`)
            setEmail('')
            setPassword('')
            setDisplayName('')
          },
          onError: (err) => setError(err.message),
        }
      )
    } else {
      login.mutate(
        { email, password },
        {
          onSuccess: (data) => {
            localStorage.setItem('nexus_token', data.access_token)
            setSuccess(`Logged in as ${data.user.display_name}`)
            setEmail('')
            setPassword('')
          },
          onError: (err) => setError(err.message),
        }
      )
    }
  }

  const isPending = login.isPending || register.isPending

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <span className="text-2xl">👤</span> Authentication
        </h2>
        <div className="flex gap-1">
          <button
            onClick={() => { setMode('login'); setError(null); setSuccess(null) }}
            className={`px-3 py-1 text-xs rounded-md transition-all ${
              mode === 'login'
                ? 'bg-indigo-600 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            Login
          </button>
          <button
            onClick={() => { setMode('register'); setError(null); setSuccess(null) }}
            className={`px-3 py-1 text-xs rounded-md transition-all ${
              mode === 'register'
                ? 'bg-indigo-600 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            Register
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-950/30 border border-red-800/50 rounded-xl p-3">
          <p className="text-sm text-red-400">{error}</p>
        </div>
      )}

      {success && (
        <div className="bg-green-950/30 border border-green-800/50 rounded-xl p-3">
          <p className="text-sm text-green-400">{success}</p>
        </div>
      )}

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3">
        <div>
          <label className="text-xs text-gray-400 block mb-1">Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
          />
        </div>

        <div>
          <label className="text-xs text-gray-400 block mb-1">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Enter password"
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
          />
        </div>

        {mode === 'register' && (
          <div>
            <label className="text-xs text-gray-400 block mb-1">Display Name</label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Your name"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
            />
          </div>
        )}

        <button
          onClick={handleSubmit}
          disabled={isPending}
          className="w-full px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 disabled:opacity-50 transition-all"
        >
          {isPending
            ? mode === 'login' ? 'Logging in...' : 'Registering...'
            : mode === 'login' ? 'Login' : 'Register'}
        </button>
      </div>
    </div>
  )
}
