import { useParams } from 'react-router-dom'
import LogSourceViewer from '../components/LogSourceViewer'

/** Standalone page for "open in new window" — the primary way to view a log
 * is now the inline closable panel on HostDetailPage; this route is the
 * extra, popped-out variant of the same viewer for when you want it in its
 * own browser window. */
export default function LogViewPage() {
  const { logSourceId } = useParams<{ logSourceId: string }>()
  if (!logSourceId) return <div className="standalone-page error">Log source not found.</div>

  return (
    <div className="standalone-page standalone-page-log">
      <LogSourceViewer logSourceId={logSourceId} />
    </div>
  )
}
