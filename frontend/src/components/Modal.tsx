import { useEffect, type ReactNode } from 'react'

interface Props {
  title: string
  subtitle?: string
  children: ReactNode
  footer?: ReactNode
  onClose: () => void
  width?: number
}

export default function Modal({ title, subtitle, children, footer, onClose, width }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-mask" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={width ? { width } : undefined}>
        <h3>{title}</h3>
        {subtitle && <div className="sub">{subtitle}</div>}
        {children}
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}
