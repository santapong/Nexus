import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { CreateListingRequest } from '../types'

export function useMarketplaceListings(skill?: string, minRating?: number) {
  return useQuery({
    queryKey: ['marketplace', skill, minRating],
    queryFn: () => api.listMarketplaceListings(skill, minRating),
    refetchInterval: 30000,
  })
}

export function useCreateListing() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: CreateListingRequest) => api.createListing(data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['marketplace'] }),
  })
}

export function usePublishListing() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.publishListing(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['marketplace'] }),
  })
}

export function useSubmitReview() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      listingId,
      rating,
      comment,
    }: {
      listingId: string
      rating: number
      comment?: string
    }) => api.submitReview(listingId, rating, comment),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['marketplace'] }),
  })
}
