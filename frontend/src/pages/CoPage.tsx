import { useState } from 'react'
import { CoCanvas } from '@/components/co/CoCanvas'
import { CoComposer } from '@/components/co/CoComposer'
import { PresentationPanel } from '@/components/co/PresentationPanel'
import { ThinkingFeed } from '@/components/co/ThinkingFeed'

/**
 * The default view: your personal assistant "Co" as a single central node
 * that expands into the live agent team DAG. Composer overlays the canvas;
 * the activity feed docks right.
 */
export function CoPage() {
  const [expanded, setExpanded] = useState(false)
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null)

  return (
    <div className="flex h-[calc(100vh-4rem)] overflow-hidden">
      <div className="relative flex-1">
        <CoCanvas
          expanded={expanded}
          selectedAgentId={selectedAgentId}
          onToggleExpanded={() => setExpanded((v) => !v)}
          onSelectAgent={setSelectedAgentId}
        />
        <div className="pointer-events-none absolute inset-x-0 bottom-6 flex justify-center px-4">
          <CoComposer />
        </div>
        <PresentationPanel />
      </div>
      <ThinkingFeed
        selectedAgentId={selectedAgentId}
        onClearSelection={() => setSelectedAgentId(null)}
      />
    </div>
  )
}
