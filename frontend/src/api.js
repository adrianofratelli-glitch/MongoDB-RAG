import axios from 'axios'

export async function getConfig() {
  const { data } = await axios.get('/api/config')
  return data
}

export async function getStatus(force = false) {
  const { data } = await axios.get('/api/status', { params: force ? { force: true } : {} })
  return data
}

export async function getHistory(threadId) {
  const { data } = await axios.get(`/api/history/${encodeURIComponent(threadId)}`)
  return data.messages || []
}

/**
 * Stream the chat over SSE (fetch + ReadableStream).
 * handlers: { onMeta(evt), onToken(delta), onDone(), onError(msg) }
 */
export async function streamChat({ question, messages, threadId, accessLevel }, handlers) {
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
        access_level: accessLevel || 'restrito',
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
