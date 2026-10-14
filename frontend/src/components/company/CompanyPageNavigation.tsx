import { Button } from '@/components/ui/button'

export function CompanyPageNavigation({ after, onChange, continuations }: {
  after: string | null; onChange: (cursor: string | null) => void;
  continuations: { label: string; cursor: string | null | undefined }[]
}) {
  const available = continuations.filter(item => item.cursor)
  if (!after && available.length === 0) return null
  return <nav aria-label="More company records" className="flex flex-wrap gap-3 border-t border-gray-800 pt-4">
    {after && <Button variant="outline" size="sm" onClick={() => onChange(null)}>First page</Button>}
    {available.map(item => <Button key={item.label} variant="outline" size="sm"
      onClick={() => onChange(item.cursor!)}>More {item.label}</Button>)}
  </nav>
}
