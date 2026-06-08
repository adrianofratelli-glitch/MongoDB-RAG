"""
API FastAPI da POC RAG — MongoDB Atlas Vector Search.

Substitui o antigo app.py (Streamlit). Expõe a lógica de RAG (busca vetorial +
reranking + geração com Claude) para o frontend React + LeafyGreen via HTTP/SSE.

Reaproveita:
  - agent.retrieve_context(query) -> (context, sources, stats)
  - config (CLIENT_NAME, DOCUMENT_TITLE, ..., QUESTIONS, FOLLOWUPS)

Rodar:  uvicorn backend.api:app --reload --port 8000  (a partir da raiz do projeto)
"""
import os
import re
import json
import time
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate

from config import (
    CLIENT_NAME,
    DOCUMENT_TITLE,
    DOCUMENT_DESCRIPTION,
    DB_NAME,
    QUESTIONS,
    FOLLOWUPS,
    DEFAULT_FOLLOWUPS,
)
from agent import retrieve_context

load_dotenv()

app = FastAPI(title="RAG · MongoDB Atlas Vector Search (POC)")

# CORS liberado para dev (o Vite também faz proxy /api -> :8000).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Metadados da stack (vitrine do Vector Search) ────────────────────────────────
EMBED_MODEL = "voyage-3"
EMBED_DIM = 1024
RERANK_MODEL = "rerank-2"
VECTOR_INDEX = "vector_index"

# ── Remove emoji inicial (mesma regra do app antigo) ─────────────────────────────
_EMOJI_RE = re.compile(
    r"^[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF️‍←-⇿⬀-⯿]+\s*"
)


def _clean(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()


# ── Status REAL do Atlas (ping de verdade, com cache curto) ──────────────────────
_status_lock = threading.Lock()
_status_cache = {"ts": 0.0, "online": False, "chunks": None}


def _ping_atlas():
    from pymongo import MongoClient

    try:
        client = MongoClient(os.environ["MONGO_URI"], serverSelectionTimeoutMS=3500)
        client.admin.command("ping")
        chunks = client[DB_NAME]["documents"].count_documents({})
        client.close()
        return True, chunks
    except Exception:
        return False, None


def get_status(force: bool = False):
    with _status_lock:
        now = time.time()
        if force or (now - _status_cache["ts"] > 15):
            online, chunks = _ping_atlas()
            _status_cache.update(ts=now, online=online, chunks=chunks)
        return _status_cache["online"], _status_cache["chunks"]


# ── Prompt (portado do app.py) ───────────────────────────────────────────────────
SYSTEM_PROMPT = """Você é um assistente especializado em {document_title} — {client_name}.
Responda usando APENAS o contexto fornecido. Seja formal, objetivo e preciso.
Se a informação não estiver no contexto, diga claramente.

FORMATAÇÃO:
- **Negrito** em valores financeiros, datas/prazos e identificadores chave.
- Bullet points ao listar mais de 2 itens.
- Tabela Markdown ao comparar múltiplas entidades, custos ou cronogramas.

Finalize com: **Fontes:** [páginas consultadas]

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


# ── Endpoints ────────────────────────────────────────────────────────────────────
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
    messages: list[dict] = []  # histórico anterior (sem a pergunta atual)


@app.post("/api/chat")
def api_chat(body: ChatBody):
    """Stream SSE: eventos {type: meta|token|done|error}."""

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
            context, sources, stats = retrieve_context(body.question)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            yield _sse(
                {
                    "type": "meta",
                    "stats": stats,
                    "sources": sources,
                    "elapsed_ms": elapsed_ms,
                    "followups": _get_followups(body.question),
                }
            )

            llm = ChatAnthropic(
                model="claude-sonnet-4-20250514",
                temperature=0,
                streaming=True,
                api_key=os.environ["ANTHROPIC_API_KEY"],
            )
            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        SYSTEM_PROMPT.format(
                            document_title=DOCUMENT_TITLE,
                            client_name=CLIENT_NAME,
                            context=context,
                        ),
                    ),
                    *[
                        ("human" if m.get("role") == "user" else "ai", m.get("content", ""))
                        for m in body.messages
                    ],
                    ("human", body.question),
                ]
            )
            for chunk in llm.stream(prompt.format_messages()):
                if chunk.content:
                    yield _sse({"type": "token", "delta": chunk.content})
            yield _sse({"type": "done"})
        except Exception as e:  # noqa: BLE001
            yield _sse(
                {
                    "type": "error",
                    "message": "Ocorreu um erro ao consultar o Atlas ou gerar a resposta. "
                    f"Tente novamente em instantes. (detalhe técnico: {type(e).__name__})",
                }
            )

    return StreamingResponse(gen(), media_type="text/event-stream")
