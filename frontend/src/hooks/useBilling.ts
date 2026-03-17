import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export function useBillingSummary(period = '30d') {
  return useQuery({
    queryKey: ['billing-summary', period],
    queryFn: () => api.getBillingSummary(period),
    refetchInterval: 60000,
  })
}

export function useBillingRecords(limit = 50) {
  return useQuery({
    queryKey: ['billing-records', limit],
    queryFn: () => api.getBillingRecords(limit),
    refetchInterval: 60000,
  })
}

export function useInvoice(period = '30d') {
  return useQuery({
    queryKey: ['invoice', period],
    queryFn: () => api.getInvoice(period),
    enabled: false, // Only fetch on demand
  })
}
