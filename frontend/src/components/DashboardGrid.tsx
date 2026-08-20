import { ActionIcon } from '@mantine/core'
import { IconX } from '@tabler/icons-react'
import { GridLayout, useContainerWidth, type Layout } from 'react-grid-layout'
import LogPanel from './LogPanel'

export interface GridPanel {
  id: string
  logSourceId: string
  resolvedPath?: string
  title: string
  x: number
  y: number
  w: number
  h: number
}

interface Props {
  panels: GridPanel[]
  /** When given, the grid is editable (drag to move, drag the corner to
   * resize) and this fires on every change with the new positions. Omit
   * for the read-only dashboard view. */
  onLayoutChange?: (layout: Layout) => void
  /** When given (together with onLayoutChange), a small remove button is
   * overlaid on each panel. */
  onRemove?: (id: string) => void
}

// Row height in px per grid unit — a freshly-added panel defaults to h=6,
// i.e. ~360px, a sensible starting height for a log panel before resizing.
const ROW_HEIGHT = 56

export default function DashboardGrid({ panels, onLayoutChange, onRemove }: Props) {
  const { width, containerRef, mounted } = useContainerWidth()
  const editable = Boolean(onLayoutChange)

  const layout: Layout = panels.map((p) => ({ i: p.id, x: p.x, y: p.y, w: p.w, h: p.h, minW: 3, minH: 3 }))

  return (
    <div ref={containerRef} style={{ flex: 1, minHeight: 200 }}>
      {mounted && (
        <GridLayout
          width={width}
          layout={layout}
          gridConfig={{ cols: 12, rowHeight: ROW_HEIGHT, margin: [12, 12], containerPadding: [0, 0], maxRows: Infinity }}
          dragConfig={{ enabled: editable }}
          resizeConfig={{ enabled: editable }}
          onLayoutChange={onLayoutChange}
          autoSize
        >
          {panels.map((p) => (
            <div key={p.id} className="dashboard-grid-item">
              {onRemove && (
                <ActionIcon
                  size="sm"
                  variant="filled"
                  color="red"
                  onClick={() => onRemove(p.id)}
                  style={{ position: 'absolute', top: 6, right: 6, zIndex: 2 }}
                  title="Remove panel"
                >
                  <IconX size={14} />
                </ActionIcon>
              )}
              <LogPanel logSourceId={p.logSourceId} resolvedPath={p.resolvedPath} title={p.title} />
            </div>
          ))}
        </GridLayout>
      )}
    </div>
  )
}
