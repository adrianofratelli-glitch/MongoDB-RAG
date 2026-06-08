import Banner from '@leafygreen-ui/banner'
import Button from '@leafygreen-ui/button'
import { Body } from '@leafygreen-ui/typography'
import { C } from '../theme'

export default function Welcome({ config, onPick }) {
  return (
    <div>
      <Banner darkMode variant="info" style={{ marginBottom: 16 }}>
        <strong style={{ color: C.text }}>Bem-vindo ao Assistente {config.client_name}</strong>
        <br />
        {config.document_description}
        <br />
        Conectado ao <strong style={{ color: C.green }}>MongoDB Atlas</strong> com busca semântica{' '}
        <em>{config.embed_model}</em> + reranking <em>{config.rerank_model}</em>.
      </Banner>

      {config.questions?.length > 0 && (
        <>
          <div className="sb-section-label" style={{ marginLeft: 0 }}>Sugestões de perguntas</div>
          <div className="sugg-grid">
            {config.questions.map((q, i) => (
              <Button key={i} darkMode onClick={() => onPick(q)} style={{ justifyContent: 'flex-start' }}>
                <Body style={{ color: C.text, textAlign: 'left' }}>{q}</Body>
              </Button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
