# Enterprise RAG Assistant 🧠

Boilerplate de **RAG (Retrieval-Augmented Generation) corporativo** com busca semântica avançada, reranking e memória persistente. Projetado para ser configurado rapidamente para qualquer cliente e qualquer tipo de documento.

> **Multi-cliente:** cada cliente usa seu próprio banco no MongoDB Atlas, configurado via variáveis de ambiente — sem tocar no código.

---

## 🏗️ Arquitetura

```mermaid
graph TD
    User([👤 Usuário]) <-->|Chat / SSE| UI[💻 React + LeafyGreen]
    UI <-->|HTTP /api| API[⚡ FastAPI]

    subgraph Pipeline RAG - Hybrid Search
        API -->|Query| EMB[🔢 VoyageAI voyage-3\nEmbedding da Query]
        EMB -->|Vetor| VS[🔍 Atlas Vector Search\nfiltro de ACL]
        API -->|Texto| LX[📝 Atlas Search BM25\nfiltro de ACL]
        VS -->|Ranking vetorial| RRF[⚖️ Reciprocal Rank Fusion]
        LX -->|Ranking léxico| RRF
        RRF -->|Candidatos fundidos| RNK[🎯 VoyageAI rerank-2\nReranking Semântico]
        RNK -->|Contexto Reordenado| LLM[🤖 Anthropic Claude\nSonnet 4.6]
    end

    LLM -->|Token Streaming| API
    API <-->|Persiste Conversa| MDB[(🍃 MongoDB Atlas\nconversations)]
```

### Fluxo detalhado

| Etapa | Componente | Descrição |
|-------|-----------|-----------|
| 1 | **Ingestão** | Documento (PDF/DOCX/TXT/CSV) → chunks → embeddings via `voyage-3` → Atlas (com `nivel_acesso` para ACL) |
| 2 | **Hybrid Search** | Pergunta → busca vetorial (ANN) **+** busca léxica (BM25) em paralelo, ambas com filtro de ACL |
| 3 | **Fusão (RRF)** | Os dois rankings são fundidos por Reciprocal Rank Fusion |
| 4 | **Reranking** | Candidatos fundidos reordenados pelo `rerank-2` → apenas os 8 mais relevantes passam |
| 5 | **Geração** | Contexto limpo + histórico da sessão → Claude Sonnet 4.6 com streaming SSE |
| 6 | **Persistência** | Conversa salva na collection `conversations` do mesmo Atlas (retomada por Thread ID) |

---

## ✨ Funcionalidades

- **Hybrid Search** — busca vetorial (`$vectorSearch`) **+** léxica (Atlas Search/BM25) fundidas por RRF
- **Reranking** — `rerank-2` da VoyageAI filtra e reordena candidatos antes do LLM
- **ACL por nível de acesso** — filtro `nivel_acesso` (público/restrito) aplicado nos dois índices
- **Streaming** — respostas em tempo real token a token (SSE) via Claude Sonnet 4.6
- **Memória persistida** — conversa salva no MongoDB e retomável por Thread ID
- **Multi-formato** — ingestão de `.pdf`, `.docx`, `.txt`, `.csv`
- **Multi-cliente** — cada cliente tem seu próprio banco, configurado via `.env`
- **Perguntas personalizadas** — sugestões e follow-ups configuráveis por `client_config.json`
- **Export** — conversa exportável em TXT ou JSON

> **Nota (POC):** o nível de acesso é selecionado na própria interface para fins de demonstração. Em produção, ele viria de um sistema de autenticação (SSO/JWT), nunca do cliente.

---

## 🛠️ Stack

| Camada | Tecnologia |
|--------|-----------|
| Interface | React + Vite + **LeafyGreen** (design system oficial MongoDB) |
| API | FastAPI (streaming SSE) |
| Banco / Vector Store | MongoDB Atlas (Vector Search + Atlas Search) |
| Embeddings & Reranker | VoyageAI (`voyage-3`, `rerank-2`) |
| LLM | Anthropic Claude Sonnet 4.6 (`claude-sonnet-4-6`) |
| Orquestração | LangGraph |
| Carregamento de docs | LangChain Community Loaders |

---

## 🚀 Setup

### 1. Clone e ambiente virtual

```bash
git clone https://github.com/adrianofratelli-glitch/MongoDB-RAG.git
cd MongoDB-RAG
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Variáveis de ambiente

Copie `.env.example` para `.env` e preencha:

```bash
cp .env.example .env
```

```env
MONGO_URI="sua_connection_string_atlas"
VOYAGE_API_KEY="sua_chave_voyage"
ANTHROPIC_API_KEY="sua_chave_anthropic"

CLIENT_ID="nome_cliente"          # usado para nomear o banco: rag_<CLIENT_ID>
CLIENT_NAME="Nome do Cliente"
DOCUMENT_TITLE="Nome do Documento"
DOCUMENT_DESCRIPTION="Descrição exibida na interface."
```

### 3. Configure o MongoDB Atlas

Execute o script de setup — ele cria as collections **e os dois índices** (vetorial `vector_index` com filtro de ACL e léxico `text_index` para o hybrid search):

```bash
python setup_db.py
```

> Os índices Atlas Search levam ~1 minuto para ficarem ativos após a criação.

### 4. Ingira o documento

```bash
# PDF, DOCX, TXT ou CSV
python ingest.py caminho/para/documento.pdf

# Para reindexar um documento já existente
python ingest.py caminho/para/documento.pdf --reset

# Para indexar como conteúdo restrito (demo de ACL)
python ingest.py caminho/para/anexo_confidencial.pdf --nivel restrito
```

> **Free tier VoyageAI:** o script usa batches conservadores com pausa de 22s entre eles para respeitar o limite de 3 RPM.

### 5. Personalize perguntas (opcional)

Copie e edite o arquivo de configuração do cliente:

```bash
cp client_config.example.json client_config.json
```

### 6. Inicie a aplicação

**Atalho (sobe backend + frontend de uma vez):**

```bash
./run.sh
```

Ou manualmente, em 2 processos:

**Backend (API FastAPI):**

```bash
uvicorn backend.api:app --reload --port 8000
```

**Frontend (React + LeafyGreen):**

```bash
cd frontend
npm install        # primeira vez
npm run dev        # abre em http://localhost:5180 (proxy /api -> :8000)
```

Abra **http://localhost:5180**. O frontend faz proxy de `/api` para o backend, sem CORS.

---

## 📁 Estrutura

```
.
├── backend/
│   └── api.py                 # API FastAPI (config / status / chat SSE)
├── frontend/                  # App React + Vite + LeafyGreen (UI oficial MongoDB)
│   └── src/
│       ├── App.jsx            # Orquestração + estado
│       ├── api.js             # axios (config/status) + fetch SSE (chat)
│       └── components/        # Sidebar, TopBar, KpiRow, ChatMessage, EngineStrip, Sources, ...
├── agent.py                   # retrieve_context (hybrid search + RRF + rerank, com ACL)
├── ingest.py                  # Ingestão multi-formato (com --nivel para ACL)
├── setup_db.py                # Setup de collections e índices (vector_index + text_index)
├── config.py                  # Configuração central via env vars
├── db.py                      # Cliente MongoDB compartilhado (pool de conexões)
├── client_config.json         # Perguntas/followups por cliente (não versionado)
├── client_config.example.json # Exemplo de configuração de cliente
├── requirements.txt
├── .env.example
├── data/                      # Documentos do cliente (não versionados)
└── assets/                    # Assets visuais do cliente (não versionados)
```

---

## ⚙️ Adicionando um novo cliente

1. Configure `.env` com os dados do novo cliente
2. Coloque o documento em `data/`
3. Copie `client_config.example.json` → `client_config.json` e personalize
4. `python setup_db.py` → `python ingest.py data/documento.pdf` → `uvicorn backend.api:app --port 8000` + `cd frontend && npm run dev`

Cada cliente usa um banco MongoDB isolado (`rag_<CLIENT_ID>`), sem interferência entre projetos.

---

## 🔑 Variáveis de ambiente — referência completa

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `MONGO_URI` | ✅ | Connection string do MongoDB Atlas |
| `VOYAGE_API_KEY` | ✅ | Chave da API VoyageAI |
| `ANTHROPIC_API_KEY` | ✅ | Chave da API Anthropic |
| `CLIENT_ID` | ✅ | ID do cliente (define nome do banco) |
| `CLIENT_NAME` | ✅ | Nome exibido na interface |
| `DOCUMENT_TITLE` | ✅ | Título do documento |
| `DOCUMENT_DESCRIPTION` | — | Descrição exibida no header |
| `DB_NAME` | — | Nome do banco (padrão: `rag_<CLIENT_ID>`) |
| `SYSTEM_PROMPT_EXTRA` | — | Instrução extra para o system prompt |
