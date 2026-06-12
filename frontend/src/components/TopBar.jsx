import Button from '@leafygreen-ui/button'
import Icon from '@leafygreen-ui/icon'
import { C } from '../theme'

export default function TopBar({ config, online, onRefresh }) {
  return (
    <div className="top-nav">
      <span style={{ fontSize: 16, fontWeight: 800, letterSpacing: '-0.02em', color: C.text }}>
        Chat Assistant
      </span>
      <span className="proto-badge">{config.client_name} · RAG POC</span>
      <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: C.muted }}>{config.document_title}</span>

      <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
        <span className={`status-pill ${online ? 'on' : 'off'}`}>
          <span className="status-dot" />
          {online ? 'Atlas Online' : 'Atlas Offline'}
        </span>
        <Button darkMode size="small" onClick={onRefresh} leftGlyph={<Icon glyph="Refresh" />}>
          Atualizar
        </Button>
      </span>
    </div>
  )
}
