import axios from 'axios'

/**
 * O backend leva alguns segundos para subir (imports pesados), e o launcher abre
 * o browser assim que a porta responde. Sem retry, a primeira carga cai na casca
 * offline e só um reload manual conserta.
 */
export async function getConfig({ retries = 4, delayMs = 800 } = {}) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      const { data } = await axios.get('/api/config', { timeout: 5000 })
      return data
    } catch (err) {
      if (attempt >= retries) throw err
      await new Promise((resolve) => setTimeout(resolve, delayMs * 2 ** attempt))
    }
  }
}

export async function getStatus(force = false) {
  const { data } = await axios.get('/api/status', { params: force ? { force: true } : {} })
  return data
}

export async function getHistory(threadId) {
  const { data } = await axios.get(`/api/history/${encodeURIComponent(threadId)}`)
  return data.messages || []
}

export async function getDocuments() {
  const { data } = await axios.get('/api/documents')
  return data
}

/** Upload a document; ingestion runs server-side as a job (poll getJob). */
export async function uploadDocument({ file, nivelAcesso = 'publico', reset = false }) {
  const form = new FormData()
  form.append('file', file)
  form.append('nivel_acesso', nivelAcesso)
  form.append('reset', String(reset))
  const { data } = await axios.post('/api/documents', form)
  return data
}

export async function getJob(jobId) {
  const { data } = await axios.get(`/api/documents/jobs/${encodeURIComponent(jobId)}`)
  return data
}

export async function deleteDocument(source) {
  const { data } = await axios.delete(`/api/documents/${encodeURIComponent(source)}`)
  return data
}

/**
 * Stream the chat over SSE (fetch + ReadableStream).
 * handlers: { onMeta(evt), onToken(delta), onDone(), onError(msg) }
 */
export async function streamChat({ question, messages, threadId, accessLevel, sources, scope }, handlers) {
  const { onMeta, onToken, onDone, onError } = handlers
  let res
  try {
    res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        messages,
        thread_id: threadId,
        // Default-deny: restricted access must be an explicit UI choice. In a
        // production deployment this value must come from authenticated claims.
        access_level: accessLevel || 'publico',
        // Empty means "every document of the active workspace" — the backend
        // resolves `scope` into the source list, so a tab never reads the other.
        sources: sources || [],
        scope: scope || 'all',
      }),
    })
  } catch {
    onError?.('Não foi possível contatar a API. O backend está rodando?')
    return
  }
  if (!res.ok || !res.body) {
    onError?.('Falha na requisição ao backend.')
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let idx
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const raw = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      const dataLine = raw.split('\n').find((l) => l.startsWith('data:'))
      if (!dataLine) continue
      let evt
      try {
        evt = JSON.parse(dataLine.slice(5).trim())
      } catch {
        continue
      }
      if (evt.type === 'meta') onMeta?.(evt)
      else if (evt.type === 'token') onToken?.(evt.delta)
      else if (evt.type === 'done') onDone?.()
      else if (evt.type === 'error') onError?.(evt.message)
    }
  }
}
