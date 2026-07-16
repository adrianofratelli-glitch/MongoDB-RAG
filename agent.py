import logging
import os
import voyageai
from typing import Annotated, TypedDict, List
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_anthropic import ChatAnthropic
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.mongodb import MongoDBSaver
from config import DB_NAME, CLIENT_NAME, DOCUMENT_TITLE, SYSTEM_PROMPT_EXTRA
from db import get_client
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("tjgo_rag.agent")

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = f"""Você é um assistente especializado em {DOCUMENT_TITLE} para {CLIENT_NAME}.

Você tem dois tipos de informação:
1. CONTEXTO DO DOCUMENTO: trechos mais relevantes, já reordenados por relevância
2. HISTÓRICO: perguntas e respostas desta sessão

Regras rigorosas de comportamento e formatação:
- Responda usando APENAS o contexto fornecido. Se não encontrar a informação, diga claramente.
- Para perguntas sobre o histórico, use as mensagens anteriores.
- DESTAQUE VISUAL: Coloque em **negrito** valores financeiros, datas/prazos e identificadores importantes.
- ESTRUTURA: Use listas (bullet points) sempre que citar mais de dois itens.
- TABELAS: Formate em tabela Markdown ao comparar múltiplas entidades, custos ou cronogramas.
{SYSTEM_PROMPT_EXTRA}

CONTEXTO DO DOCUMENTO:
{{context}}"""


class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    context: str
    sources: List[dict]


ALL_ACCESS = ["publico", "restrito"]
RRF_K = 60  # standard Reciprocal Rank Fusion constant

# Lazy singleton, mirrors db.get_client() — avoids re-instantiating per call.
_voyage = None


def _get_voyage() -> voyageai.Client:
    global _voyage
    if _voyage is None:
        _voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
    return _voyage


def _vector_pipeline(embedding, top_k, access_levels):
    vs = {
        "index": "vector_index",
        "path": "embedding",
        "queryVector": embedding,
        "numCandidates": top_k * 15,
        "limit": top_k,
    }
    if access_levels:
        vs["filter"] = {"metadata.nivel_acesso": {"$in": access_levels}}
    return [
        {"$vectorSearch": vs},
        {"$project": {"text": 1, "metadata": 1,
                      "vector_score": {"$meta": "vectorSearchScore"}}},
    ]


def _lexical_pipeline(query, top_k, access_levels):
    must = [{"text": {"query": query, "path": "text"}}]
    flt = [{"in": {"path": "metadata.nivel_acesso", "value": access_levels}}] if access_levels else []
    return [
        {"$search": {"index": "text_index", "compound": {"must": must, "filter": flt}}},
        {"$limit": top_k},
        {"$project": {"text": 1, "metadata": 1,
                      "search_score": {"$meta": "searchScore"}}},
    ]


def retrieve_context(query: str, top_k: int = 15,
                     access_levels: list | None = None) -> tuple[str, list[dict], dict]:
    """Hybrid search: vector ∪ lexical retrieval -> RRF -> rerank-2, with an ACL filter.

    access_levels: allowed access levels (e.g. ["publico"]). None means full access.
    """
    history_keywords = ["pergunt", "anterior", "sessão", "conversa", "falei", "histórico"]
    if any(k in query.lower() for k in history_keywords):
        return "Responda com base no histórico da conversa.", [], {}

    levels = access_levels if access_levels else ALL_ACCESS

    voyage = _get_voyage()
    collection = get_client()[DB_NAME]["documents"]

    embedding = voyage.embed([query], model="voyage-3", input_type="query").embeddings[0]

    # 1) Retrieve from both modalities (two aggregations)
    vector_results = list(collection.aggregate(_vector_pipeline(embedding, top_k, levels)))
    try:
        lexical_results = list(collection.aggregate(_lexical_pipeline(query, top_k, levels)))
    except Exception:
        logger.exception("lexical search failed — falling back to vector-only")
        lexical_results = []  # tolerant: if the lexical index fails, fall back to vector only

    # 2) Reciprocal Rank Fusion (RRF): merge the two rankings by _id
    fused: dict = {}

    def _fuse(rows, score_key, matched):
        for rank, r in enumerate(rows, start=1):
            key = str(r["_id"])
            entry = fused.setdefault(key, {
                "text": r["text"], "metadata": r["metadata"],
                "vector_score": 0.0, "search_score": 0.0,
                "rrf": 0.0, "matched_by": set(),
            })
            entry["rrf"] += 1.0 / (RRF_K + rank)
            entry["matched_by"].add(matched)
            if score_key in r and r[score_key] is not None:
                entry[score_key] = round(float(r[score_key]), 4)

    _fuse(vector_results, "vector_score", "vetorial")
    _fuse(lexical_results, "search_score", "léxico")

    if not fused:
        return "Nenhum contexto encontrado.", [], {}

    candidates = sorted(fused.values(), key=lambda x: x["rrf"], reverse=True)

    # 3) rerank-2 (VoyageAI) over the fused set
    documents = [c["text"] for c in candidates]
    try:
        rr = voyage.rerank(query, documents, model="rerank-2", top_k=min(8, len(documents)))
        top_results = []
        for item in rr.results:
            c = candidates[item.index]
            c["rerank_score"] = round(item.relevance_score, 4)
            top_results.append(c)
    except Exception:
        logger.exception("rerank failed — falling back to RRF order")
        top_results = candidates[:8]
        for c in top_results:
            c["rerank_score"] = round(c.get("vector_score") or c.get("search_score") or 0, 4)

    parts = []
    sources = []
    seen_pages: set = set()
    for r in top_results:
        page = r["metadata"].get("page", "?")
        source = r["metadata"].get("source", "")
        parts.append(f"[Página {page} | {source}]\n{r['text']}")
        if page not in seen_pages:
            sources.append({
                "page": page,
                "source": source,
                "nivel_acesso": r["metadata"].get("nivel_acesso", "publico"),
                "matched_by": sorted(r["matched_by"]),
                "vector_score": r.get("vector_score", 0),
                "rerank_score": r.get("rerank_score", 0),
                "preview": r["text"][:130],
            })
            seen_pages.add(page)

    stats = {
        "num_candidates": top_k * 15,        # $vectorSearch numCandidates
        "vector_hits": len(vector_results),  # returned by vector search
        "lexical_hits": len(lexical_results),  # returned by lexical search (Atlas Search)
        "fused": len(fused),                 # unique candidates after RRF
        "reranked": len(top_results),        # after rerank-2
        "index": "vector_index + text_index",
        "embed_model": "voyage-3",
        "rerank_model": "rerank-2",
        "embed_dim": len(embedding),
        "access_levels": levels,
        "hybrid": True,
    }

    return "\n\n---\n\n".join(parts), sources, stats


# Lazy: avoid instantiating ChatAnthropic at import time, which would break the
# API if ANTHROPIC_API_KEY were absent even when the graph is not used.
_llm = None


def _get_llm() -> ChatAnthropic:
    global _llm
    if _llm is None:
        _llm = ChatAnthropic(model=MODEL, temperature=0)
    return _llm


def retrieve_node(state: AgentState) -> AgentState:
    query = state["messages"][-1].content
    context, sources, _ = retrieve_context(query)
    return {"context": context, "sources": sources}


def generate_node(state: AgentState) -> AgentState:
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="messages"),
    ])
    response = (prompt | _get_llm()).invoke({
        "context": state["context"],
        "messages": state["messages"],
    })
    return {"messages": [response]}


def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("generate", generate_node)
    builder.set_entry_point("retrieve")
    builder.add_edge("retrieve", "generate")
    builder.add_edge("generate", END)
    checkpointer = MongoDBSaver(get_client(), db_name=DB_NAME)
    return builder.compile(checkpointer=checkpointer)
