import { useParams } from 'react-router-dom'
import { Text } from '@mantine/core'
import LogSourceViewer from '../components/LogSourceViewer'

/** Standalone page for "open in new window" — the primary way to view a log
 * is now the inline drawer on AgentDetailPage; this route is the extra,
 * popped-out variant of the same viewer for when you want it in its own
 * browser window. */
export default function LogViewPage() {
  const { logSourceId } = useParams<{ logSourceId: string }>()
  if (!logSourceId)
    return (
      <div className="standalone-page">
        <Text c="red">Log source not found.</Text>
      </div>
    )

  return (
    <div className="standalone-page standalone-page-log">
      <LogSourceViewer logSourceId={logSourceId} />
    </div>
  )
}
