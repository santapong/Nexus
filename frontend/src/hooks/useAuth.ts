import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'

export function useLogin() {
  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      api.login(email, password),
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
  })
}
