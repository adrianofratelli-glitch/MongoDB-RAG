import Button from '@leafygreen-ui/button'
import Icon from '@leafygreen-ui/icon'
import { C } from '../theme'

export default function TopBar({ config, online, onRefresh }) {
  return (
    <div
      style={{
        display: 'flex', alignItems: 'center', gap: 14,
        background: 'linear-gradient(90deg, #0D2437 0%, #00141c 70%)',
        borderBottom: `2px solid ${C.green}`, borderRadius: '8px 8px 0 0',
        padding: '12px 18px', marginBottom: 16,
      }}
    >
      <span style={{ fontSize: 16, fontWeight: 800, color: C.text }}>Chat Assistant</span>
      <span style={{ color: C.muted }}>·</span>
      <span style={{ fontFamily: 'var(--mono)', fontSize: 13, color: C.sub }}>{config.client_name}</span>
      <span style={{ color: C.muted }}>·</span>
      <span style={{ fontFamily: 'var(--mono)', fontSize: 13, color: C.sub }}>{config.document_title}</span>

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
