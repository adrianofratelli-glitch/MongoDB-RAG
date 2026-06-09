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
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from config import (
    CLIENT_NAME,
    DOCUMENT_TITLE,
    DOCUMENT_DESCRIPTION,
    DB_NAME,
    QUESTIONS,
    FOLLOWUPS,
    DEFAULT_FOLLOWUPS,
)
from agent import retrieve_context, MODEL
from db import get_client

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
    try:
        client = get_client()
        client.admin.command("ping")
        chunks = client[DB_NAME]["documents"].count_documents({})
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


# ── ACL: perfil de acesso → níveis permitidos ───────────────────────────────────
def _levels_for(access_level: str) -> list:
    # "publico" só vê público; "restrito" vê tudo (público + restrito)
    return ["publico"] if access_level == "publico" else ["publico", "restrito"]


# ── Memória de conversa persistida no MongoDB (mesma plataforma) ─────────────────
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
        pass  # persistência nunca deve derrubar o chat


def _load_conversation(thread_id):
    try:
        doc = get_client()[DB_NAME]["conversations"].find_one({"_id": thread_id})
        if not doc:
            return []
        return [{"role": m.get("role"), "content": m.get("content")}
                for m in doc.get("messages", [])]
    except Exception:
        return []


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
    messages: list[dict] = []          # histórico anterior (sem a pergunta atual)
    thread_id: str | None = None       # para persistir a conversa
    access_level: str = "restrito"     # "publico" | "restrito" (perfil de acesso)


@app.get("/api/history/{thread_id}")
def api_history(thread_id: str):
    """Retoma uma conversa persistida no MongoDB."""
    return {"thread_id": thread_id, "messages": _load_conversation(thread_id)}


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
            context, sources, stats = retrieve_context(
                body.question, access_levels=_levels_for(body.access_level)
            )
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
                model=MODEL,
                temperature=0,
                streaming=True,
                api_key=os.environ["ANTHROPIC_API_KEY"],
            )
            # Mensagens construídas diretamente (sem ChatPromptTemplate): o
            # contexto do PDF e o histórico podem conter chaves `{}`, que um
            # template interpretaria como variáveis e quebraria a requisição.
            lc_messages = [
                SystemMessage(
                    content=SYSTEM_PROMPT.format(
                        document_title=DOCUMENT_TITLE,
                        client_name=CLIENT_NAME,
                        context=context,
                    )
                ),
                *[
                    (HumanMessage if m.get("role") == "user" else AIMessage)(
                        content=m.get("content", "")
                    )
                    for m in body.messages
                ],
                HumanMessage(content=body.question),
            ]
            full = ""
            for chunk in llm.stream(lc_messages):
                if chunk.content:
                    full += chunk.content
                    yield _sse({"type": "token", "delta": chunk.content})

            # Persiste a conversa no MongoDB (mesma plataforma dos vetores)
            _save_conversation(
                body.thread_id,
                body.messages
                + [{"role": "user", "content": body.question},
                   {"role": "assistant", "content": full}],
            )
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
