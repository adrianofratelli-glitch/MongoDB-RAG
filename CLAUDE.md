# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

RAG proof-of-concept assistant on MongoDB Atlas Vector Search. Reference deployment answers
questions about the TJGO PDTIC 2025-2027 plan, but the stack is document- and tenant-agnostic —
each tenant runs against its own Atlas database, configured entirely via `.env`.

## Commands

```bash
./run.sh              # start backend (:8180) + frontend (:5180), heals partial state, safe to re-run
./run.sh stop
./run.sh status

# manual (from project root, .venv activated)
uvicorn backend.api:app --reload --port 8180
cd frontend && npm run dev     # :5180, proxies /api -> :8180

cd frontend && npm run build
cd frontend && npm run lint

python setup_db.py                              # create collections + vector_index + text_index
python ingest.py path/to/document.pdf           # ingest (PDF/DOCX/TXT/CSV/MD/HTML/JSON/XLSX/PPTX)
python ingest.py path/to/document.pdf --reset   # re-index existing doc
python ingest.py path/to/annex.pdf --nivel restrito   # ingest as access-restricted content
```

python -m unittest discover -s tests -v   # 12 tests, pure logic — no live Atlas/Voyage/Anthropic needed

docker build -t tjgo-rag .
docker run --env-file .env -p 8080:8080 tjgo-rag   # single container, nginx + uvicorn, proxies /api

## Architecture

Request flow: React+LeafyGreen UI -> FastAPI (`backend/api.py`) -> hybrid retrieval
(`agent.py::retrieve_context`) -> Claude generation, streamed back over SSE.

- **`agent.py`** — core retrieval pipeline, used by both the API and the LangGraph agent:
  1. Embed the query with VoyageAI `voyage-3`.
  2. Run vector search (`$vectorSearch` on `vector_index`) and lexical search (Atlas Search
     `$search` on `text_index`) in parallel, each filtered by `metadata.nivel_acesso` (ACL).
  3. Fuse both rankings with Reciprocal Rank Fusion (RRF, k=60).
  4. Re-rank the fused candidates with VoyageAI `rerank-2`, keep top 8.
  5. Also exposes a LangGraph `build_graph()` (retrieve -> generate node graph) with
     `MongoDBSaver` checkpointing — not used by `backend/api.py`, which builds messages and
     streams directly instead (see below).
- **`backend/api.py`** — FastAPI app; does NOT use `agent.build_graph()`. It calls
  `retrieve_context()` directly, then constructs `SystemMessage`/`HumanMessage`/`AIMessage`
  by hand (not a `ChatPromptTemplate`) because the retrieved PDF context or history may
  contain literal `{}` characters that a template would misparse as variables. Streams
  tokens via SSE (`type: meta|token|done|error`).
- **`ingest.py`** — multi-format loader: PDF/DOCX/TXT/CSV/HTML via LangChain community
  loaders, plus lightweight custom loaders for Markdown, JSON, XLSX (openpyxl), and PPTX
  (python-pptx) to avoid the heavy `unstructured` dependency. Chunks with
  `RecursiveCharacterTextSplitter` (800/150 overlap), embeds in small batches with a 22s
  pause (VoyageAI free tier: 3 req/min), tags each chunk with `nivel_acesso`.
- **`config.py`** — all tenant configuration is env-driven: `CLIENT_ID` (also names the
  database as `rag_<CLIENT_ID>`), `CLIENT_NAME`, `DOCUMENT_TITLE`, `DOCUMENT_DESCRIPTION`,
  `SYSTEM_PROMPT_EXTRA`. Starter questions/follow-ups load from `client_config.json`
  (gitignored; copy from `client_config.example.json`) with hardcoded PT-BR defaults.
- **`db.py`** — single shared `MongoClient` (module-level singleton), reused everywhere for
  connection pooling; never instantiate a new `MongoClient` per request. `ingest.py` and
  `backend/api.py` both reuse it; `setup_db.py` opens its own (one-shot admin script, closes
  on exit).
- **`observability.py`** — structured logging (`LOG_JSON=1` for JSON logs) and in-process
  metrics. `backend/api.py` wires it up: request-id middleware on every response, `GET
  /api/metrics` (per-route counters/latency), `GET /api/health`.
- **Access control (`nivel_acesso`)** — POC-only concept: `"publico"` (public) or `"restrito"`
  (restricted), selected client-side in the UI. Filtered on both vector and lexical search
  stages. In production this must come from real auth (SSO/JWT), never from client input.
- **Conversations** — persisted in the `conversations` collection of the tenant's Atlas DB,
  resumable by `thread_id` (`GET /api/history/{thread_id}`). Persistence failures are
  swallowed (`_save_conversation`/`_load_conversation`) so chat never breaks on a DB hiccup.
- **Multi-tenancy** — one Atlas database per tenant (`rag_<CLIENT_ID>`); adding a tenant means
  new `.env` values + `data/` document + `client_config.json`, no code changes.
- **CORS / API exposure** — `ALLOWED_ORIGINS` env var (comma-separated) restricts which
  origins can call the API; defaults to the local Vite dev server only. `/api/chat` validates
  the question is non-empty and under `MAX_QUESTION_LENGTH` (4000 chars) before spending an
  LLM call on it. There is still no authentication on any endpoint — `access_level` is
  trusted from the request body (documented POC limitation) and `/api/history/{thread_id}`
  returns any conversation to whoever knows/guesses the `thread_id` (a client-generated
  UUIDv4). Add real auth (SSO/JWT) before any non-demo deployment.

## Frontend

`frontend/src/` — React + Vite + LeafyGreen (MongoDB's design system). Key files:
`App.jsx` (state/orchestration), `api.js` (config/status calls + SSE chat stream),
`components/` (Sidebar, TopBar, KpiRow, ChatMessage, EngineStrip, Sources).
