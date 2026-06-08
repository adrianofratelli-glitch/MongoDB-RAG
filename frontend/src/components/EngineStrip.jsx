import { C } from '../theme'

// Vitrine do Atlas Vector Search: candidatos -> recuperados -> reranqueados + metadados.
export default function EngineStrip({ stats, elapsedMs }) {
  if (!stats) return null
  const cand = stats.num_candidates ?? '—'
  const vec = stats.vector_hits ?? '—'
  const rer = stats.reranked ?? '—'
  const dim = stats.embed_dim ?? '—'
  const idx = stats.index ?? 'vector_index'
  const embm = stats.embed_model ?? 'voyage-3'
  const rerm = stats.rerank_model ?? 'rerank-2'

  return (
    <div className="engine-strip">
      <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: 1.4, color: C.green, textTransform: 'uppercase' }}>
        ⚡ Atlas Vector Search
      </span>
      <span style={{ fontSize: 11, color: C.text }}>
        <span className="hint" title="numCandidates — vetores que a busca aproximada (ANN/HNSW) do Atlas examina internamente">
          {cand} candidatos
        </span>
        <span style={{ color: C.muted }}> → </span>
        <span className="hint" title="limit — documentos que o $vectorSearch retorna (vizinhos mais próximos por cosseno)">
          {vec} recuperados
        </span>
        <span style={{ color: C.muted }}> → </span>
        <strong className="hint" style={{ color: C.green }} title="documentos mantidos após reordenação por relevância (rerank-2 · VoyageAI)">
          {rer} reranqueados
        </strong>
      </span>
      <span style={{ fontSize: 10, color: C.sub, marginLeft: 'auto' }}>
        {embm} · {dim}d&nbsp;&nbsp;|&nbsp;&nbsp;{rerm}&nbsp;&nbsp;|&nbsp;&nbsp;idx{' '}
        <code style={{ color: C.green }}>{idx}</code>
        {elapsedMs != null && (
          <>
            &nbsp;&nbsp;|&nbsp;&nbsp;<strong style={{ color: C.green }}>{elapsedMs} ms</strong>
          </>
        )}
      </span>
    </div>
  )
}
