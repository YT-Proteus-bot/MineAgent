import { useState } from 'react'
import Modal from './Modal'

interface Props {
  title: string
  subtitle?: string
  defaultValue?: string
  placeholder?: string
  confirmText?: string
  onConfirm: (value: string) => void
  onClose: () => void
}

export default function PromptModal({
  title,
  subtitle,
  defaultValue = '',
  placeholder,
  confirmText = '确定',
  onConfirm,
  onClose,
}: Props) {
  const [value, setValue] = useState(defaultValue)
  const submit = () => {
    onConfirm(value.trim())
    onClose()
  }
  return (
    <Modal
      title={title}
      subtitle={subtitle}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>取消</button>
          <button className="primary" onClick={submit} disabled={!value.trim()}>
            {confirmText}
          </button>
        </>
      }
    >
      <label className="field">
        <span>名称</span>
        <input
          autoFocus
          value={value}
          placeholder={placeholder}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && value.trim()) submit()
          }}
        />
      </label>
    </Modal>
  )
}
