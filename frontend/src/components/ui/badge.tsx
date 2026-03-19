import { type HTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium transition-colors',
  {
    variants: {
      variant: {
        default: 'bg-gray-700 text-gray-200',
        success: 'bg-green-700 text-green-100',
        destructive: 'bg-red-700 text-red-100',
        warning: 'bg-yellow-700 text-yellow-100',
        info: 'bg-blue-700 text-blue-100',
        purple: 'bg-purple-700 text-purple-100',
        outline: 'border border-gray-600 text-gray-300',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
