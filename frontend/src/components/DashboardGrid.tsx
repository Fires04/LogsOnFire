import LogPanel from './LogPanel'

export interface GridPanel {
  id: string
  logSourceId: string
  resolvedPath?: string
  title: string
  width: number
}

export default function DashboardGrid({ panels }: { panels: GridPanel[] }) {
  return (
    <div className="dashboard-grid">
      {panels.map((p) => (
        <div key={p.id} className="dashboard-grid-cell" style={{ gridColumn: `span ${p.width}` }}>
          <LogPanel logSourceId={p.logSourceId} resolvedPath={p.resolvedPath} title={p.title} />
        </div>
      ))}
    </div>
  )
}
