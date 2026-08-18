# Assistente RAG Multi-tenant — arquitetura e princípios

> Primeiro dos três prompts que eu uso pra levantar essa PoV do zero. Aqui está o critério de arquitetura, o pipeline de recuperação e as regras de custo e exposição. Coleções, índices e pipelines em `02-mongodb.md`; tela e roteiro em `03-interface-fluxos.md`.

---

## O que eu quero construir

Um assistente RAG sobre **MongoDB Atlas Vector Search**, com um deployment de referência respondendo perguntas sobre um documento público de planejamento de TI do setor público — mas com a stack **agnóstica de documento e de tenant**.

O critério que define se a arquitetura ficou certa: **adicionar um tenant novo tem que ser valores novos no `.env`, o documento em `data/`, e um `client_config.json`. Zero mudança de código.**

Se em algum momento adicionar um cliente exigir tocar em Python, a abstração falhou e eu quero saber antes de seguir.

## O ponto técnico não é "fazer RAG"

Fazer RAG qualquer um faz em uma tarde. O ponto aqui é a **qualidade da recuperação**: híbrido com fusão e reranking, não similaridade vetorial pura.

Quatro estágios:

1. **Embedding** da pergunta com VoyageAI `voyage-3`.
2. **Busca vetorial e busca lexical em paralelo** — `$vectorSearch` e `$search` do Atlas Search, **ambas filtradas por `metadata.nivel_acesso`**.
3. **Reciprocal Rank Fusion**, k=60, fundindo os dois ranqueamentos.
4. **Rerank** com VoyageAI `rerank-2`, mantendo o top 8.

Depois disso, geração com Claude sobre o contexto recuperado, transmitida por SSE.

Por que os quatro estágios em vez de só `$vectorSearch` — e isso precisa estar no README, porque é a pergunta que sempre vem:

- **Vetorial sozinho** erra em sigla, número de norma e nome próprio. Documento de planejamento público é feito disso.
- **Lexical sozinho** erra quando o usuário pergunta com outras palavras.
- **RRF** combina os dois ranqueamentos sem precisar normalizar scores de escalas diferentes — que, na prática, nem são comparáveis.
- **Rerank** é o que separa "8 chunks que casaram" de "os 8 chunks que respondem". É o estágio que mais melhora a resposta final por token gasto.

As duas buscas rodam de verdade em paralelo (uma thread pra vetorial, a lexical na thread atual), e **cada uma tolera a falha da outra**: se o índice vetorial cair, a lexical sozinha ainda responde, e vice-versa, com o log dizendo qual caiu. O rerank também tem fallback — falhou, mantém a ordem do RRF e copia o score disponível. Degradar pra metade do pipeline é muito melhor que devolver erro — e a `EngineStrip` na tela vai mostrar a assimetria sozinha.

Duas otimizações que valem estar desde cedo:

- **Cache LRU de embedding de pergunta** (chave = pergunta normalizada). As perguntas prontas da tela de boas-vindas são clicadas várias vezes numa demo; não faz sentido pagar embedding toda vez.
- **Curto-circuito de histórico**: pergunta que se refere explicitamente à conversa ("o que eu perguntei antes") **não roda recuperação nenhuma** — responde a partir do histórico. Mas usa **frases inteiras**, nunca termos soltos: "sessão", "anterior" e "histórico" aparecem em pergunta legítima sobre o documento e matariam a recuperação.

## Uma decisão de implementação que parece detalhe e não é

A API **não usa** o `build_graph()` do LangGraph. Ela chama `retrieve_context()` direto e constrói `SystemMessage`/`HumanMessage`/`AIMessage` **na mão**, e não por `ChatPromptTemplate`.

O motivo é concreto: o contexto recuperado do PDF ou o histórico podem conter chaves `{}` literais, que um template interpretaria como variável e quebraria em runtime — só com certos documentos, só com certas perguntas. É o tipo de bug que aparece na demo.

O `build_graph()` pode existir e funcionar (nós retrieve → generate, com checkpoint `MongoDBSaver`), mas **fora do caminho da API**. Deixa isso comentado no código pra ninguém "unificar" depois achando que está limpando.

## Multi-tenancy

Um database Atlas por tenant: `rag_<CLIENT_ID>`.

Toda configuração vem de env, lida por um `config.py`:

| Variável | Papel |
|---|---|
| `CLIENT_ID` | identifica o tenant **e nomeia o database** |
| `CLIENT_NAME` | nome exibido |
| `DOCUMENT_TITLE` | título do documento na UI |
| `DOCUMENT_DESCRIPTION` | descrição |
| `SYSTEM_PROMPT_EXTRA` | instruções extras de domínio no system prompt |

Perguntas iniciais e follow-ups vêm de um `client_config.json` (gitignored, com um `.example` versionado), com defaults pt-BR.

## Controle de acesso

Conceito **só do PoC**: `nivel_acesso` é `"publico"` ou `"restrito"`, escolhido no lado do cliente na UI, e com default `publico` nos dois lados (front e back) — o caminho mais permissivo nunca pode ser o default implícito.

Ele é filtrado nos **dois** estágios de busca — vetorial e lexical, e nos dois como filtro nativo do índice. Isso é o correto arquiteturalmente e vale explicar em demo: filtrar só depois da fusão deixaria conteúdo restrito **influenciar o ranqueamento** antes de ser descartado. O usuário não veria o conteúdo, mas a ordem do que ele vê teria sido alterada por documento que ele não pode ler.

**Em produção isso tem que vir de autenticação real (SSO/JWT), nunca de input do cliente.** Documenta como limitação, em letras grandes, não como feature.

Na tela é um seletor justamente porque o objetivo da demo é mostrar a **mesma pergunta devolvendo conjuntos de fontes diferentes** conforme o nível.

## Custo e limites — porque RAG vaza dinheiro devagar

Três lugares onde o gasto cresce sem ninguém perceber, e o que fazer em cada um:

- **Histórico do cliente cresce sem teto.** O front manda a conversa inteira a cada turno. Limita o que é de fato encaminhado, por número de mensagens **e** por caracteres, senão o custo por turno sobe conversa afora.
- **Concorrência de geração é limitada por semáforo.** Saturado, recusa em vez de enfileirar — requisição de LLM presa numa demo é pior que requisição recusada.
- **Teto de token de saída.** Resposta longa demais não é melhor, é só mais cara.

E tem o **sumário do documento (TOC) no bloco cacheado do system**. Esse detalhe vale explicar: a Anthropic só efetiva o prompt cache acima de ~1024 tokens, e o system prompt do tenant sozinho não chega lá — o `cache_control` seria um no-op silencioso. O sumário, que é estável entre turnos, empurra o bloco acima do mínimo e passa a valer cache de verdade. Ele é montado uma vez, cacheado em memória por uma hora, e limitado por caracteres.

Os índices de TTL nas conversas e no histórico persistido também estão aí pra limitar crescimento — dado de demo que fica pra sempre vira custo pra sempre.

## Exposição da API

- `ALLOWED_ORIGINS` (separado por vírgula) restringindo quais origens chamam a API. Default: só o dev server local do Vite.
- `/api/chat` valida que a pergunta é não-vazia e menor que 4000 caracteres **antes de gastar uma chamada de LLM com ela**.
- `/api/health` responde **503** quando o Atlas não responde, não 200 com um campo dizendo que está ruim.
- `thread_id` é validado como UUID no path — não como string livre.

### O que ainda não tem, e precisa estar escrito

- **Não há autenticação em nenhum endpoint.**
- `access_level` é confiado do corpo da requisição.
- `/api/history/{thread_id}` devolve qualquer conversa pra quem souber ou adivinhar o `thread_id` (um UUIDv4 gerado no cliente).

**Autenticação real antes de qualquer deployment que não seja demo.** Não deixa isso implícito no README — enuncia.

## Estrutura

Layout Python plano na raiz, sem pacote aninhado:

| Arquivo | Papel |
|---|---|
| `agent.py` | pipeline de recuperação (usado pela API e pelo grafo) + `build_graph()` |
| `backend/api.py` | app FastAPI, streaming SSE, montagem manual de mensagens |
| `ingest.py` | loader multi-formato, chunking, embedding em lotes |
| `db.py` | `MongoClient` singleton |
| `config.py` | configuração de tenant, toda por env |
| `setup_db.py` | criação de coleções e índices |
| `observability.py` | log estruturado (`LOG_JSON=1`), request-id, `/api/metrics`, `/metrics` Prometheus, `/api/health` |

## Como rodar

```bash
./run.sh              # backend :8180 + frontend :5180 — cura estado parcial, seguro re-executar
./run.sh stop
./run.sh status
```

Manual, da raiz com a venv ativada:

```bash
uvicorn backend.api:app --reload --port 8180
cd frontend && npm run dev      # :5180, proxia /api -> :8180
cd frontend && npm run build && npm run lint
```

Testes: `python -m unittest discover -s tests -v` — **lógica pura, sem Atlas, Voyage ou Anthropic ao vivo.**

Docker em container único: nginx serve o `dist/` e proxia `/api` pro uvicorn, mesma origem, sem CORS. Em desenvolvimento quem faz esse papel é o proxy do Vite — o `ALLOWED_ORIGINS` no backend só existe por causa do dev server.

## Como quero que você trabalhe

- Nenhuma configuração de tenant em código. Se você precisar de um valor novo, ele vai pro `config.py` + `.env.example`.
- Nenhum `MongoClient` novo fora do singleton.
- O `meta` do SSE sempre antes do primeiro `token`.
- O filtro de acesso nos **dois** estágios de busca, nunca depois da fusão.
- Cada estágio da recuperação tolera a falha do outro, e diz no log qual caiu.
- Toda limitação de segurança fica escrita e visível. Prefiro enunciar antes que perguntem.

## Ordem de trabalho

1. `config.py` e `db.py` — a base multi-tenant antes de qualquer feature.
2. `setup_db.py` criando as coleções e os **dois** índices (vetorial e de texto).
3. `ingest.py` com um formato só (PDF), validando o chunking e o embedding ponta a ponta.
4. Os outros formatos, um a um.
5. `retrieve_context()` — primeiro só vetorial, depois só lexical, depois o RRF, **e só então o rerank**. Mede a diferença em cada passo.
6. A API com SSE, testada no `curl` antes de existir React.
7. Conversas e retomada por `thread_id`.
8. Os limites de custo (histórico, concorrência, saída) e o sumário no bloco cacheado.
9. Frontend, com o `EngineStrip` desde o começo.

O passo 5 fatiado assim é importante: eu quero **saber** quanto cada estágio agregou, com exemplos concretos. Isso vira argumento em cliente — e se algum estágio não agregar nada no corpus real, quero descobrir isso agora, não depois.

## Fronteiras do PoC

- Sem autenticação; `nivel_acesso` vem do cliente.
- `/api/history/{thread_id}` é adivinhável pelo design atual.
- Embedding limitado pelo tier gratuito da VoyageAI — a pausa de 22s é consequência, não escolha.
- Métricas em processo, resetam no restart.
- Os testes cobrem lógica pura; a qualidade de recuperação depende de avaliação contra o corpus real.
