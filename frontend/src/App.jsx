import { useEffect, useRef, useState } from 'react'
import Banner from '@leafygreen-ui/banner'
import Button from '@leafygreen-ui/button'
import { Body } from '@leafygreen-ui/typography'
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

const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2))

export default function App() {
  const [config, setConfig] = useState(null)
  const [status, setStatus] = useState({ online: false, chunks: null })
  const [messages, setMessages] = useState([])
  const [streaming, setStreaming] = useState(false)
  const [threadId, setThreadId] = useState(uuid())
  const [totalQueries, setTotalQueries] = useState(0)
  const [error, setError] = useState(null)
  const [reconnecting, setReconnecting] = useState(false)
  const [accessLevel, setAccessLevel] = useState('restrito') // 'publico' | 'restrito'
  const endRef = useRef(null)

  useEffect(() => {
    getConfig().then(setConfig).catch(() => setError('Falha ao carregar a configuração da API.'))
    refreshStatus()
  }, [])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const refreshStatus = async (force = false) => {
    try {
      setStatus(await getStatus(force))
    } catch {
      setStatus({ online: false, chunks: null })
    }
  }

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
          setMessages((prev) => prev.slice(0, -2)) // desfaz user + placeholder
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
                    <Button key={i} darkMode onClick={() => send(fq)} style={{ justifyContent: 'flex-start' }}>
                      <Body style={{ color: C.text }}>{fq}</Body>
                    </Button>
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
