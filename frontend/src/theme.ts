import { createTheme, type MantineColorsTuple } from '@mantine/core'

// Same brand accent as the pre-Mantine design (--accent: #d1451f / dark
// #ff6a3d) — a 10-shade tuple so Mantine components (buttons, links,
// focus rings) pick it up consistently instead of the default blue.
const flame: MantineColorsTuple = [
  '#fff2ee',
  '#ffe0d4',
  '#ffbfa8',
  '#ff9a78',
  '#ff7a50',
  '#ff6a3d',
  '#f5602f',
  '#d1451f',
  '#b83a19',
  '#9c2f12',
]

export const theme = createTheme({
  primaryColor: 'flame',
  colors: { flame },
  defaultRadius: 'md',
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  fontFamilyMonospace:
    "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace",
  headings: { fontWeight: '700' },
})

// Status colors used for agent/log-panel connectivity indicators — kept as
// plain values (not Mantine theme colors) since they're semantic states
// (online/live, offline/idle, connecting, error), not brand colors.
export const statusColor = {
  online: 'teal',
  offline: 'gray',
  connecting: 'yellow',
  error: 'red',
} as const
