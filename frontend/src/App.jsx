import { useEffect, useRef, useState } from 'react'
import Banner from '@leafygreen-ui/banner'
import { getConfig, getStatus, getHistory, streamChat } from './api'
import Sidebar from './components/Sidebar'
import TopBar from './components/TopBar'
import KpiRow from './components/KpiRow'
import Welcome from './components/Welcome'
import OfflineHero from './components/OfflineHero'
import ChatMessage from './components/ChatMessage'
import ChatInput from './components/ChatInput'
import Footer from './components/Footer'
import { C } from './theme'

const uuid = () => {
  if (crypto.randomUUID) return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

const OFFLINE_CONFIG = {
  client_name: 'RAG PoC',
  document_title: 'documento configurado',
  document_description: 'Assistente documental com recuperação híbrida.',
  db_name: 'indisponível',
  questions: [],
  embed_model: 'Voyage AI',
  rerank_model: 'Voyage AI',
}

export default function App() {
  const [config, setConfig] = useState(null)
  const [status, setStatus] = useState({ online: false, chunks: null })
  const [messages, setMessages] = useState([])
  const [streaming, setStreaming] = useState(false)
  const [threadId, setThreadId] = useState(uuid())
  const [totalQueries, setTotalQueries] = useState(0)
  const [error, setError] = useState(null)
  const [reconnecting, setReconnecting] = useState(false)
  const [accessLevel, setAccessLevel] = useState('publico') // produção deriva isso de claims autenticadas
  const endRef = useRef(null)

  const refreshStatus = async (force = false) => {
    try {
      setStatus(await getStatus(force))
    } catch {
      setStatus({ online: false, chunks: null })
    }
  }

  useEffect(() => {
    getConfig().then(setConfig).catch(() => {
      setConfig(OFFLINE_CONFIG)
      setError('A API não respondeu. Inicie o backend e tente reconectar.')
    })
    getStatus()
      .then(setStatus)
      .catch(() => setStatus({ online: false, chunks: null }))
  }, [])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const chunksRead = messages.reduce((a, m) => a + (m.sources?.length || 0), 0)

  const send = async (question) => {
    if (streaming) return
    setError(null)
    const history = messages.map(({ role, content }) => ({ role, content }))
    setMessages((prev) => [...prev, { role: 'user', content: question }, { role: 'assistant', content: '' }])
    setTotalQueries((n) => n + 1)
    setStreaming(true)

    await streamChat(
      { question, messages: history, threadId, accessLevel },
      {
        onMeta: (evt) =>
          setMessages((prev) => {
            const next = [...prev]
            next[next.length - 1] = {
              ...next[next.length - 1],
              stats: evt.stats,
              sources: evt.sources,
              elapsedMs: evt.elapsed_ms,
              followups: evt.followups,
            }
            return next
          }),
        onToken: (delta) =>
          setMessages((prev) => {
            const next = [...prev]
            next[next.length - 1] = { ...next[next.length - 1], content: next[next.length - 1].content + delta }
            return next
          }),
        onDone: () => setStreaming(false),
        onError: (msg) => {
          setStreaming(false)
          setMessages((prev) => prev.slice(0, -2)) // undo the user + placeholder messages
          setTotalQueries((n) => Math.max(0, n - 1))
          setError(msg)
          refreshStatus(true)
        },
      },
    )
  }

  const reconnect = async () => {
    setReconnecting(true)
    await refreshStatus(true)
    setReconnecting(false)
  }
  const newChat = () => {
    setMessages([])
    setThreadId(uuid())
    setTotalQueries(0)
    setError(null)
  }
  const resume = async (id) => {
    setError(null)
    try {
      const hist = await getHistory(id)
      setThreadId(id)
      setMessages(hist)
      setTotalQueries(hist.filter((m) => m.role === 'user').length)
      if (hist.length === 0) setError('Nenhuma conversa encontrada para esse Thread ID.')
    } catch {
      setError('Não foi possível retomar a conversa.')
    }
  }

  if (!config) {
    return <div style={{ padding: 40, color: C.sub }}>Carregando…</div>
  }

  const last = messages[messages.length - 1]
  const showFollowups = !streaming && last?.role === 'assistant' && last.followups?.length > 0

  return (
    <div className="app-shell">
      <Sidebar
        config={config}
        status={status}
        threadId={threadId}
        totalQueries={totalQueries}
        chunksRead={chunksRead}
        messages={messages}
        onResume={resume}
        onNewChat={newChat}
        accessLevel={accessLevel}
        onAccessLevel={setAccessLevel}
      />
      <main className="main">
        <TopBar config={config} online={status.online} onRefresh={() => refreshStatus(true)} />
        <KpiRow totalQueries={totalQueries} chunksRead={chunksRead} documentTitle={config.document_title} />

        {error && (
          <Banner darkMode variant="danger" dismissible onClose={() => setError(null)} style={{ marginBottom: 14 }}>
            {error}
          </Banner>
        )}

        {!status.online ? (
          <OfflineHero dbName={config.db_name} onReconnect={reconnect} reconnecting={reconnecting} />
        ) : (
          <>
            {messages.length === 0 ? (
              <Welcome config={config} onPick={send} />
            ) : (
              messages.map((m, i) => <ChatMessage key={i} msg={m} />)
            )}

            {showFollowups && (
              <div style={{ marginTop: 6 }}>
                <div className="sb-section-label" style={{ marginLeft: 0 }}>Perguntas relacionadas</div>
                <div className="sugg-grid">
                  {last.followups.map((fq, i) => (
                    <button key={i} className="sugg-card" onClick={() => send(fq)}>
                      <span className="sugg-num">Continuar {String(i + 1).padStart(2, '0')}</span>
                      <span className="sugg-text">{fq}</span>
                      <span className="sugg-arrow">→</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div ref={endRef} />
            <ChatInput placeholder={`Pergunte sobre ${config.document_title}…`} disabled={streaming} onSend={send} />
          </>
        )}

        <Footer />
      </main>
    </div>
  )
}
