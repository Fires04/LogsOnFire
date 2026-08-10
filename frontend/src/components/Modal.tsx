import type { ReactNode } from 'react'

interface Props {
  onClose: () => void
  children: ReactNode
  wide?: boolean
  /** Near-fullscreen variant, for content (like a live log panel) that wants
   * real vertical space instead of shrink-wrapping to its contents. */
  big?: boolean
}

/** A minimal modal overlay — click the backdrop or press the button inside to close. */
export default function Modal({ onClose, children, wide, big }: Props) {
  const className = ['modal-content', wide && 'modal-wide', big && 'modal-big'].filter(Boolean).join(' ')
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className={className} onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  )
}
