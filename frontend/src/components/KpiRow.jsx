import Card from '@leafygreen-ui/card'
import { C } from '../theme'

function Kpi({ label, value, sub, color, border }) {
  return (
    <Card darkMode style={{ padding: '13px 16px', borderTop: `3px solid ${border}`, borderTopLeftRadius: 0, borderTopRightRadius: 0 }}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value" style={{ color }}>{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </Card>
  )
}

export default function KpiRow({ totalQueries, chunksRead, documentTitle }) {
  return (
    <div className="kpi-row">
      <Kpi label="Perguntas" value={totalQueries} sub="na sessão atual" color={C.green} border={C.green} />
      <Kpi label="Chunks Lidos" value={chunksRead} sub="Vector Search hits" color={C.mint} border={C.greenMed} />
      <Kpi label="Documento" value={(documentTitle || '').slice(0, 18)} sub="indexado no Atlas" color={C.green} border={C.greenDark} />
      <Kpi label="Modelo" value="Claude Sonnet" sub="streaming LLM" color={C.greenMed} border={C.greenMed} />
    </div>
  )
}
