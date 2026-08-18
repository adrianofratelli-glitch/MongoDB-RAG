# Assistente RAG — MongoDB Atlas Vector Search

Faça uma pergunta em linguagem natural a um documento de planejamento de 200 páginas e receba uma resposta com citações em segundos. Busca vetorial e lexical rodam em paralelo no Atlas, o RRF funde os ranqueamentos, um re-ranker escolhe as melhores passagens, e o Claude responde usando só elas — em streaming, token a token.

Agnóstico de tenant por design: nenhum nome de cliente, documento ou marca vive no repositório. Um novo tenant é um `.env`, um PDF e um arquivo JSON.

## A demo em 4 passos

**1. Escolha um perfil de acesso e uma pergunta.** O perfil (público / restrito) é o filtro de ACL aplicado às *duas* etapas de busca, com negação por padrão.

![Tela inicial com o seletor de perfil de acesso e as perguntas iniciais](docs/screenshots/01-home.png)

**2. Pergunte.** A consulta vira embedding com o `voyage-3` e roda `$vectorSearch` e Atlas Search (BM25) em paralelo, cada um já filtrado por nível de acesso.

**3. Veja o pipeline se explicar.** O RRF funde os dois ranqueamentos, o `rerank-2` reordena, os 8 melhores chunks viram o contexto — e a UI mostra qual etapa produziu o quê.

![Resposta chegando em streaming com o pipeline de recuperação mostrado etapa por etapa](docs/screenshots/02-answer.png)

**4. Confira as fontes.** Toda resposta carrega as passagens e páginas de onde veio, então dá para verificar em vez de confiar.

![Passagens citadas como fonte, com os números de página](docs/screenshots/03-sources.png)

> Os screenshots rodam contra um tenant real; os nomes da organização e do documento foram substituídos por nomes neutros.

## Como uma pergunta é respondida

```mermaid
graph TD
    User([User]) <-->|Chat / SSE| UI[React + LeafyGreen]
    UI <-->|HTTP /api| API[FastAPI]
    API -->|query| EMB[voyage-3 embedding]
    EMB --> VS[Atlas Vector Search + ACL filter]
    API --> LX[Atlas Search BM25 + ACL filter]
    VS --> RRF[Reciprocal Rank Fusion]
    LX --> RRF
    RRF --> RNK[rerank-2]
    RNK --> LLM[Claude Sonnet 4.6]
    LLM -->|token streaming| API
    API <-->|conversation| MDB[(Atlas · conversations)]
```

Se um dos dois índices falhar, o outro sustenta a consulta. O bloco estável de instruções (incluindo um sumário do documento) fica em cache na API da Anthropic, então turnos repetidos custam menos. As conversas são persistidas no MongoDB e retomadas pelo thread ID.

A ingestão aceita PDF, DOCX, TXT, CSV, Markdown, HTML, JSON, XLSX e PPTX.

> Prova de conceito: o nível de acesso é escolhido na UI para fins de demonstração. Em produção viria da autenticação (SSO / JWT), nunca do cliente.

## Como rodar

```bash
python3 -m venv .venv && source .venv/bin/activate
# Setup/ingestão multiformato (inclui as dependências enxutas da API)
pip install -r requirements-ingest.txt
cp .env.example .env          # chaves + valores do tenant
python setup_db.py            # coleções + vector_index + text_index
python ingest.py data/document.pdf
cp client_config.example.json client_config.json   # perguntas iniciais (opcional)
./run.sh                      # backend :8180, frontend :5180
```

Por padrão, o launcher serve o build otimizado do frontend sem watcher. Para editar com HMR, rode `POV_DEV=1 ./run.sh`; o build só é refeito quando fontes, lockfile ou configuração mudam.

```env
MONGO_URI=
VOYAGE_API_KEY=
ANTHROPIC_API_KEY=
CLIENT_ID=tenant_id           # o banco vira rag_<CLIENT_ID>
CLIENT_NAME=Tenant Name
DOCUMENT_TITLE=Document Title
DOCUMENT_DESCRIPTION=Exibido no cabeçalho
```

Os índices de busca do Atlas levam cerca de um minuto para ficarem consultáveis. Ingira conteúdo restrito com `--nivel restrito`, reindexe com `--reset`. O tier gratuito da VoyageAI permite 3 requisições por minuto, então a ingestão gera embeddings em lotes pequenos com uma pausa (`VOYAGE_SLEEP_S`) e insere cada lote conforme avança, para que uma interrupção não perca o progresso.

Opcionais: `DB_NAME`, `SYSTEM_PROMPT_EXTRA`, `ALLOWED_ORIGINS`.

Testes: `python -m unittest discover -s tests -v` — lógica pura, sem serviços ao vivo.

## Fronteira de produção

Histórico do chat, tamanho do sumário, tokens de saída e streams RAG concorrentes são limitados; a imagem roda como UID 10001 atrás do nginx com cabeçalhos de segurança. O filtro por nível de acesso é aplicado nos dois caminhos de recuperação, mas o nível selecionado ainda vem do cliente nesta PoV. Uma implantação externa exige tenant e claims de ACL derivados de SSO/JWT; nunca confie no `access_level` vindo da requisição.

## Adicionando um tenant

Defina os valores do tenant no `.env`, coloque o documento em `data/`, customize o `client_config.json` e então rode `setup_db.py` → `ingest.py` → `run.sh`. Cada tenant ganha o próprio banco (`rag_<CLIENT_ID>`). `data/`, `assets/` e `client_config.json` estão no gitignore — nada específico de tenant chega ao repositório.

## Organização

```
backend/api.py     app FastAPI (config / status / chat SSE / métricas)
frontend/          React + Vite + LeafyGreen
agent.py           busca híbrida + RRF + rerank, com ACL
ingest.py          ingestão multiformato (--nivel define o nível de acesso)
setup_db.py        coleções e os dois índices de busca
config.py db.py    configuração e cliente Mongo compartilhado
observability.py   logging estruturado + /api/metrics
```

## Stack

React + Vite + LeafyGreen · FastAPI (SSE) · MongoDB Atlas Vector Search + Atlas Search · VoyageAI `voyage-3` / `rerank-2` · Claude Sonnet 4.6 · loaders da comunidade LangChain.
