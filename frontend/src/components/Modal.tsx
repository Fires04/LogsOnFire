import { Modal as MantineModal } from '@mantine/core'
import type { ReactNode } from 'react'

interface Props {
  onClose: () => void
  children: ReactNode
  title?: string
  wide?: boolean
  /** Near-fullscreen variant, for content (like a live log panel) that wants
   * real vertical space instead of shrink-wrapping to its contents. */
  big?: boolean
}

/** Thin wrapper over Mantine's Modal so every call site keeps the same
 * onClose/wide/big API it had before the Mantine migration. */
export default function Modal({ onClose, children, title, wide, big }: Props) {
  return (
    <MantineModal
      opened
      onClose={onClose}
      title={title}
      size={big ? '95%' : wide ? 'xl' : 'md'}
      centered
      overlayProps={{ backgroundOpacity: 0.55, blur: 2 }}
      styles={big ? { body: { height: '85vh', display: 'flex', flexDirection: 'column' }, content: { display: 'flex', flexDirection: 'column' } } : undefined}
    >
      {children}
    </MantineModal>
  )
}
