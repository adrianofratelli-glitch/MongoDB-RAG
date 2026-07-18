"""
FastAPI backend for the RAG proof of concept on MongoDB Atlas Vector Search.

Exposes the RAG pipeline (vector search + re-ranking + generation with Claude)
to the React + LeafyGreen frontend over HTTP/SSE.

Reuses:
  - agent.retrieve_context(query) -> (context, sources, stats)
  - config (CLIENT_NAME, DOCUMENT_TITLE, ..., QUESTIONS, FOLLOWUPS)

Run:  uvicorn backend.api:app --reload --port 8180  (from the project root)
"""
import logging
import os
import re
import json
import time
import threading
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

import observability
from config import (
    CLIENT_NAME,
    DOCUMENT_TITLE,
    DOCUMENT_DESCRIPTION,
    DB_NAME,
    QUESTIONS,
    FOLLOWUPS,
    DEFAULT_FOLLOWUPS,
    SYSTEM_PROMPT_EXTRA,
)
from agent import retrieve_context, MODEL
from db import get_client

load_dotenv()
observability.setup_logging()
logger = logging.getLogger("rag_poc")

app = FastAPI(title="RAG · MongoDB Atlas Vector Search (POC)")

# CORS: restricted to known origins by default (the Vite dev server proxies
# /api -> :8180, so it never needs a cross-origin allowance in dev). Set
# ALLOWED_ORIGINS to a comma-separated list for other deployments.
_allowed_origins = [
    o.strip() for o in os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:5180,http://127.0.0.1:5180"
    ).split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def _request_observability(request: Request, call_next):
    """request_id on every response + per-route latency/error counters at /api/metrics."""
    request_id = request.headers.get("x-request-id") or uuid4().hex[:16]
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        observability.metrics.observe(request.url.path, 500, (time.perf_counter() - start) * 1000)
        logger.exception("unhandled error request_id=%s path=%s", request_id, request.url.path)
        raise
    elapsed_ms = (time.perf_counter() - start) * 1000
    observability.metrics.observe(request.url.path, response.status_code, elapsed_ms)
    response.headers["X-Request-Id"] = request_id
    return response


@app.get("/api/metrics")
def api_metrics():
    """In-process counters: requests/errors/latency per route + business counters."""
    return observability.metrics.snapshot()


@app.get("/api/health")
def api_health():
    return {"status": "ok"}

MAX_QUESTION_LENGTH = 4000

# Client-supplied chat history grows unbounded across a long conversation —
# cap what we actually forward so token spend doesn't creep up turn after turn.
MAX_HISTORY_MESSAGES = 16

# Stack metadata (surfaced in the UI)
EMBED_MODEL = "voyage-3"
EMBED_DIM = 1024
RERANK_MODEL = "rerank-2"
VECTOR_INDEX = "vector_index"

# Strip a leading emoji from configured question/follow-up strings
_EMOJI_RE = re.compile(
    r"^[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF️‍←-⇿⬀-⯿]+\s*"
)


def _clean(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()


# Real Atlas status (actual ping, with a short cache)
_status_lock = threading.Lock()
_status_cache = {"ts": 0.0, "online": False, "chunks": None}


def _ping_atlas():
    try:
        client = get_client()
        client.admin.command("ping")
        # estimated_document_count reads collection metadata — O(1) instead of a
        # full scan; exactness doesn't matter for a status badge.
        chunks = client[DB_NAME]["documents"].estimated_document_count()
        return True, chunks
    except Exception:
        logger.exception("Atlas ping failed")
        return False, None


def get_status(force: bool = False):
    with _status_lock:
        now = time.time()
        if force or (now - _status_cache["ts"] > 15):
            online, chunks = _ping_atlas()
            _status_cache.update(ts=now, online=online, chunks=chunks)
        return _status_cache["online"], _status_cache["chunks"]


# Static instruction template — identical on every request regardless of which
# document chunks were retrieved. Kept separate from CONTEXTO below so it can
# be sent as its own cached block (see api_chat): the retrieved context always
# differs per query and can't be cached, but this ~120-token instruction block
# can, on every chat turn within the cache TTL.
# Kept in Portuguese so the assistant answers end users in their language.
SYSTEM_PROMPT_STATIC = """Você é um assistente especializado em {document_title} — {client_name}.
Responda usando APENAS o contexto fornecido. Seja formal, objetivo e preciso.
Se a informação não estiver no contexto, diga claramente.

FORMATAÇÃO:
- **Negrito** em valores financeiros, datas/prazos e identificadores chave.
- Bullet points ao listar mais de 2 itens.
- Tabela Markdown ao comparar múltiplas entidades, custos ou cronogramas.

Finalize com: **Fontes:** [páginas consultadas]
{extra}"""

SYSTEM_PROMPT = SYSTEM_PROMPT_STATIC + "\n\nCONTEXTO:\n{context}"

# Document outline (TOC) appended to the cached system block. Anthropic only
# caches prefixes >= 1024 tokens; the instructions alone (~120 tokens) never
# reach that, so the cache_control marker would be a no-op. The outline —
# first-chunk preview of every page — is stable between requests (changes only
# on re-ingestion), pushes the block well past the minimum, and doubles as a
# map that helps the model cite the right pages.
_outline_lock = threading.Lock()
_outline_cache = {"ts": 0.0, "text": ""}
_OUTLINE_TTL_S = 3600


def _get_document_outline() -> str:
    with _outline_lock:
        now = time.time()
        if now - _outline_cache["ts"] < _OUTLINE_TTL_S and _outline_cache["text"]:
            return _outline_cache["text"]
        try:
            rows = get_client()[DB_NAME]["documents"].aggregate([
                {"$sort": {"metadata.page": 1, "metadata.chunk_id": 1}},
                {"$group": {
                    "_id": "$metadata.page",
                    "source": {"$first": "$metadata.source"},
                    "preview": {"$first": "$text"},
                }},
                {"$sort": {"_id": 1}},
            ])
            lines = [
                f"p.{r['_id']}: {' '.join(r['preview'].split())[:160]}"
                for r in rows
            ]
            text = "SUMÁRIO DO DOCUMENTO (página: início do conteúdo):\n" + "\n".join(lines) if lines else ""
        except Exception:
            logger.exception("document outline build failed — caching disabled this turn")
            text = ""
        _outline_cache.update(ts=now, text=text)
        return text


def _get_followups(query: str):
    q = query.lower()
    for key, suggestions in FOLLOWUPS.items():
        if key in q:
            return [_clean(s) for s in suggestions]
    return [_clean(s) for s in DEFAULT_FOLLOWUPS]


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _track_usage(chunk_agg) -> None:
    """Surfaces Claude token spend (incl. cache hits) at /api/metrics."""
    if chunk_agg is None:
        return
    usage = getattr(chunk_agg, "usage_metadata", None) or {}
    observability.metrics.bump("anthropic_input_tokens", usage.get("input_tokens", 0))
    observability.metrics.bump("anthropic_output_tokens", usage.get("output_tokens", 0))
    details = usage.get("input_token_details") or {}
    observability.metrics.bump("anthropic_cache_read_tokens", details.get("cache_read", 0))
    observability.metrics.bump("anthropic_cache_write_tokens", details.get("cache_creation", 0))


# Access control: map an access profile to the allowed levels.
# Default-deny: only the exact value "restrito" unlocks restricted content —
# any other/unknown value from the client falls back to public-only.
def _levels_for(access_level: str) -> list:
    return ["publico", "restrito"] if access_level == "restrito" else ["publico"]


# Conversation memory persisted in MongoDB (same platform as the vectors)
def _save_conversation(thread_id, messages):
    if not thread_id:
        return
    from datetime import datetime, timezone
    try:
        get_client()[DB_NAME]["conversations"].update_one(
            {"_id": thread_id},
            {"$set": {
                "client": CLIENT_NAME,
                "document": DOCUMENT_TITLE,
                "messages": messages,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
    except Exception:
        logger.exception("conversation persistence failed thread_id=%s", thread_id)  # must never break the chat


def _load_conversation(thread_id):
    try:
        doc = get_client()[DB_NAME]["conversations"].find_one({"_id": thread_id})
        if not doc:
            return []
        return [{"role": m.get("role"), "content": m.get("content")}
                for m in doc.get("messages", [])]
    except Exception:
        logger.exception("conversation load failed thread_id=%s", thread_id)
        return []


# Endpoints
@app.get("/api/config")
def api_config():
    return {
        "client_name": CLIENT_NAME,
        "document_title": DOCUMENT_TITLE,
        "document_description": DOCUMENT_DESCRIPTION,
        "db_name": DB_NAME,
        "questions": [_clean(q) for q in QUESTIONS[:8]],
        "embed_model": EMBED_MODEL,
        "embed_dim": EMBED_DIM,
        "rerank_model": RERANK_MODEL,
        "index": VECTOR_INDEX,
    }


@app.get("/api/status")
def api_status(force: bool = False):
    online, chunks = get_status(force=force)
    return {"online": online, "chunks": chunks, "db_name": DB_NAME}


class ChatBody(BaseModel):
    question: str
    messages: list[dict] = []          # prior history (excluding the current question)
    thread_id: str | None = None       # used to persist the conversation
    access_level: str = "publico"      # "publico" | "restrito" — default-deny


@app.get("/api/history/{thread_id}")
def api_history(thread_id: str):
    """Resume a conversation persisted in MongoDB."""
    return {"thread_id": thread_id, "messages": _load_conversation(thread_id)}


@app.post("/api/chat")
def api_chat(body: ChatBody):
    """SSE stream of {type: meta|token|done|error} events."""

    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be empty")
    if len(question) > MAX_QUESTION_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"question exceeds {MAX_QUESTION_LENGTH} characters",
        )

    def gen():
        online, _ = get_status()
        if not online:
            yield _sse(
                {
                    "type": "error",
                    "message": "Não foi possível conectar ao MongoDB Atlas. "
                    "Verifique se o cluster está ativo (não pausado) e se seu IP "
                    "está liberado na Access List, depois tente novamente.",
                }
            )
            return
        try:
            t0 = time.perf_counter()
            context, sources, stats = retrieve_context(
                question, access_levels=_levels_for(body.access_level)
            )
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            yield _sse(
                {
                    "type": "meta",
                    "stats": stats,
                    "sources": sources,
                    "elapsed_ms": elapsed_ms,
                    "followups": _get_followups(question),
                }
            )

            llm = ChatAnthropic(
                model=MODEL,
                temperature=0,
                streaming=True,
                api_key=os.environ["ANTHROPIC_API_KEY"],
                default_headers={"api-key": os.environ["ANTHROPIC_API_KEY"]},
            )
            static_instructions = SYSTEM_PROMPT_STATIC.format(
                document_title=DOCUMENT_TITLE, client_name=CLIENT_NAME, extra=SYSTEM_PROMPT_EXTRA,
            )
            outline = _get_document_outline()
            if outline:
                static_instructions = f"{static_instructions}\n\n{outline}"
            # Build the messages directly (no ChatPromptTemplate): the PDF context
            # and history may contain `{}` braces, which a template would treat as
            # variables and fail on.
            # System content as two blocks: the static instructions (identical
            # every turn, marked cacheable) then the per-query retrieved context
            # (always different, never cacheable).
            lc_messages = [
                SystemMessage(content=[
                    {"type": "text", "text": static_instructions,
                     "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": f"CONTEXTO:\n{context}"},
                ]),
                *[
                    (HumanMessage if m.get("role") == "user" else AIMessage)(
                        content=m.get("content", "")
                    )
                    for m in body.messages[-MAX_HISTORY_MESSAGES:]
                ],
                HumanMessage(content=question),
            ]
            full = ""
            chunk_agg = None
            for chunk in llm.stream(lc_messages):
                if chunk.content:
                    full += chunk.content
                    yield _sse({"type": "token", "delta": chunk.content})
                chunk_agg = chunk if chunk_agg is None else chunk_agg + chunk
            _track_usage(chunk_agg)

            # Persist the conversation in MongoDB (same platform as the vectors)
            _save_conversation(
                body.thread_id,
                body.messages
                + [{"role": "user", "content": question},
                   {"role": "assistant", "content": full}],
            )
            yield _sse({"type": "done"})
        except Exception as e:  # noqa: BLE001
            logger.exception("chat turn failed thread_id=%s", body.thread_id)
            yield _sse(
                {
                    "type": "error",
                    "message": "Ocorreu um erro ao consultar o Atlas ou gerar a resposta. "
                    f"Tente novamente em instantes. (detalhe técnico: {type(e).__name__})",
                }
            )

    return StreamingResponse(gen(), media_type="text/event-stream")
