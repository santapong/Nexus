import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '../api/client'

export function useLogin() {
  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      api.login(email, password),
    onSuccess: () => {
      toast.success('Logged in successfully')
    },
    onError: () => {
      toast.error('Login failed')
    },
  })
}

export function useRegister() {
  return useMutation({
    mutationFn: ({
      email,
      password,
      displayName,
    }: {
      email: string
      password: string
      displayName: string
    }) => api.register(email, password, displayName),
    onSuccess: () => {
      toast.success('Account created successfully')
    },
    onError: () => {
      toast.error('Registration failed')
    },
  })
}
