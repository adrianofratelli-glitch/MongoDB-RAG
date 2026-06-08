import ExpandableCard from '@leafygreen-ui/expandable-card'
import { C } from '../theme'

function SourceCard({ i, s }) {
  const pct = Math.round((s.rerank_score ?? 0) * 100)
  const vpct = Math.round((s.vector_score ?? 0) * 100)
  let fill = '#889397'
  if (pct >= 85) fill = C.green
  else if (pct >= 65) fill = '#F97316'
  const label = `Página ${s.page}${s.source ? ` · ${s.source}` : ''}`
  return (
    <div className="src-card">
      <div className="src-head">
        <span style={{ color: C.muted }}>#{i} · {label}</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ color: C.sub }}>vetorial {vpct}%</span>
          <span style={{ color: C.muted }}>→</span>
          <span style={{ fontWeight: 700, color: fill, background: 'rgba(0,0,0,0.3)', padding: '1px 7px', borderRadius: 4 }}>
            rerank {pct}%
          </span>
        </span>
      </div>
      <div className="src-track">
        <div className="src-fill" style={{ width: `${pct}%`, background: fill }} />
      </div>
      <p style={{ fontSize: 12, color: C.sub, margin: '6px 0 0', lineHeight: 1.6, borderLeft: `2px solid ${fill}55`, paddingLeft: 8 }}>
        {s.preview}…
      </p>
    </div>
  )
}

export default function Sources({ sources }) {
  if (!sources || sources.length === 0) return null
  return (
    <div style={{ marginTop: 10 }}>
      <ExpandableCard
        title={`${sources.length} fonte(s) · MongoDB Atlas Vector Search`}
        darkMode
      >
        {sources.map((s, i) => (
          <SourceCard key={i} i={i + 1} s={s} />
        ))}
      </ExpandableCard>
    </div>
  )
}
