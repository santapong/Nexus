import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '../api/client'
import type { AttachmentRef } from '../types'

/** Upload a file to /api/uploads; resolves to an AttachmentRef whose id
 * is passed to createTask (ADR-089). */
export function useUploadFile() {
  return useMutation<AttachmentRef, Error, File>({
    mutationFn: (file: File) => api.uploadFile(file),
    onError: (error, file) => {
      toast.error(`Upload failed: ${file.name}`, { description: error.message })
    },
  })
}
