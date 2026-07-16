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
logger = logging.getLogger("tjgo_rag")

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
        chunks = client[DB_NAME]["documents"].count_documents({})
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


# System prompt — kept in Portuguese so the assistant answers TJGO users in
# their language (the source document is Portuguese).
SYSTEM_PROMPT = """Você é um assistente especializado em {document_title} — {client_name}.
Responda usando APENAS o contexto fornecido. Seja formal, objetivo e preciso.
Se a informação não estiver no contexto, diga claramente.

FORMATAÇÃO:
- **Negrito** em valores financeiros, datas/prazos e identificadores chave.
- Bullet points ao listar mais de 2 itens.
- Tabela Markdown ao comparar múltiplas entidades, custos ou cronogramas.

Finalize com: **Fontes:** [páginas consultadas]
{extra}

CONTEXTO:
{context}"""


def _get_followups(query: str):
    q = query.lower()
    for key, suggestions in FOLLOWUPS.items():
        if key in q:
            return [_clean(s) for s in suggestions]
    return [_clean(s) for s in DEFAULT_FOLLOWUPS]


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# Access control: map an access profile to the allowed levels
def _levels_for(access_level: str) -> list:
    # "publico" sees public only; "restrito" sees everything (public + restricted)
    return ["publico"] if access_level == "publico" else ["publico", "restrito"]


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
    access_level: str = "restrito"     # "publico" | "restrito" (access profile)


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
            )
            # Build the messages directly (no ChatPromptTemplate): the PDF context
            # and history may contain `{}` braces, which a template would treat as
            # variables and fail on.
            lc_messages = [
                SystemMessage(
                    content=SYSTEM_PROMPT.format(
                        document_title=DOCUMENT_TITLE,
                        client_name=CLIENT_NAME,
                        context=context,
                        extra=SYSTEM_PROMPT_EXTRA,
                    )
                ),
                *[
                    (HumanMessage if m.get("role") == "user" else AIMessage)(
                        content=m.get("content", "")
                    )
                    for m in body.messages
                ],
                HumanMessage(content=question),
            ]
            full = ""
            for chunk in llm.stream(lc_messages):
                if chunk.content:
                    full += chunk.content
                    yield _sse({"type": "token", "delta": chunk.content})

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
