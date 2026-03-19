import { LoginPanel } from '@/components/auth/LoginPanel'

export function LoginPage() {
  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-6">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex h-12 w-12 rounded-xl bg-indigo-600 items-center justify-center text-white font-bold text-xl mb-3">
            N
          </div>
          <h1 className="text-2xl font-bold text-white">NEXUS</h1>
          <p className="text-gray-500 text-sm mt-1">Agentic AI Company as a Service</p>
        </div>
        <LoginPanel />
      </div>
    </div>
  )
}
