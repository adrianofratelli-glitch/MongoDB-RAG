import logging
import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import voyageai
from config import DB_NAME
from db import get_client
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("rag_poc.agent")

MODEL = "claude-sonnet-4-6"

ALL_ACCESS = ["publico", "restrito"]
RRF_K = 60  # standard Reciprocal Rank Fusion constant

# Lazy singleton, mirrors db.get_client() — avoids re-instantiating per call.
_voyage = None


def _get_voyage() -> voyageai.Client:
    global _voyage
    if _voyage is None:
        _voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
    return _voyage


# Cache em memória de embeddings de consulta (pergunta normalizada -> embedding).
# Perguntas iniciais repetidas (starter questions) pulam a chamada à Voyage.
_EMBED_CACHE_MAX = 256
_embed_cache: "OrderedDict[str, list]" = OrderedDict()
_embed_cache_lock = threading.Lock()


def _embed_query(voyage: voyageai.Client, query: str) -> list:
    key = " ".join(query.lower().split())
    with _embed_cache_lock:
        if key in _embed_cache:
            _embed_cache.move_to_end(key)  # LRU
            return _embed_cache[key]
    embedding = voyage.embed([query], model="voyage-3", input_type="query").embeddings[0]
    with _embed_cache_lock:
        _embed_cache[key] = embedding
        _embed_cache.move_to_end(key)
        while len(_embed_cache) > _EMBED_CACHE_MAX:
            _embed_cache.popitem(last=False)
    return embedding


def _vector_pipeline(embedding, top_k, access_levels, sources=None):
    vs = {
        "index": "vector_index",
        "path": "embedding",
        "queryVector": embedding,
        "numCandidates": top_k * 15,
        "limit": top_k,
    }
    conditions = []
    if access_levels:
        conditions.append({"metadata.nivel_acesso": {"$in": access_levels}})
    if sources:
        conditions.append({"metadata.source": {"$in": sources}})
    if conditions:
        vs["filter"] = conditions[0] if len(conditions) == 1 else {"$and": conditions}
    return [
        {"$vectorSearch": vs},
        {"$project": {"text": 1, "metadata": 1,
                      "vector_score": {"$meta": "vectorSearchScore"}}},
    ]


def _lexical_pipeline(query, top_k, access_levels, sources=None):
    must = [{"text": {"query": query, "path": "text"}}]
    flt = []
    if access_levels:
        flt.append({"in": {"path": "metadata.nivel_acesso", "value": access_levels}})
    if sources:
        flt.append({"in": {"path": "metadata.source", "value": sources}})
    return [
        {"$search": {"index": "text_index", "compound": {"must": must, "filter": flt}}},
        {"$limit": top_k},
        {"$project": {"text": 1, "metadata": 1,
                      "search_score": {"$meta": "searchScore"}}},
    ]


def retrieve_context(query: str, top_k: int = 15,
                     access_levels: list | None = None,
                     sources: list | None = None) -> tuple[str, list[dict], dict]:
    """Hybrid search: vector ∪ lexical retrieval -> RRF -> rerank-2, with an ACL filter.

    access_levels: allowed access levels (e.g. ["publico"]). None means full access.
    sources: restrict retrieval to these `metadata.source` values (the documents
    picked in the UI). None/empty means every indexed document in the tenant DB.
    """
    # Somente frases que referenciam explicitamente a conversa — termos soltos
    # ("sessão", "anterior", "histórico") aparecem em perguntas legítimas sobre
    # o documento e matariam a recuperação.
    history_phrases = [
        "o que eu perguntei",
        "minha pergunta anterior",
        "pergunta que fiz",
        "o que falei antes",
    ]
    if any(p in query.lower() for p in history_phrases):
        return "Responda com base no histórico da conversa.", [], {}

    levels = access_levels if access_levels else ALL_ACCESS

    voyage = _get_voyage()
    collection = get_client()[DB_NAME]["documents"]

    embedding = _embed_query(voyage, query)
    vector_pipeline = _vector_pipeline(embedding, top_k, levels, sources)
    lexical_pipeline = _lexical_pipeline(query, top_k, levels, sources)

    # 1) Retrieve from both modalities in parallel (two independent aggregations)
    def _run_vector():
        try:
            return list(collection.aggregate(vector_pipeline))
        except Exception:
            logger.exception("vector search failed — falling back to lexical-only")
            return []  # tolerant: if the vector index fails, fall back to lexical only

    def _run_lexical():
        try:
            return list(collection.aggregate(lexical_pipeline))
        except Exception:
            logger.exception("lexical search failed — falling back to vector-only")
            return []  # tolerant: if the lexical index fails, fall back to vector only

    with ThreadPoolExecutor(max_workers=2) as pool:
        vector_future = pool.submit(_run_vector)
        lexical_results = _run_lexical()
        vector_results = vector_future.result()

    # 2) Reciprocal Rank Fusion (RRF): merge the two rankings by _id
    fused: dict = {}

    def _fuse(rows, score_key, matched):
        for rank, r in enumerate(rows, start=1):
            key = str(r["_id"])
            entry = fused.setdefault(key, {
                "chunk_id": key,
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

    requested_sources = list(sources or [])
    parts = []
    sources = []
    # Dedupe by chunk, not by page: a Markdown corpus has no pagination, so every
    # chunk carries page 0 and a page-keyed set collapsed all eight reranked
    # passages into a single source card.
    seen_chunks: set = set()
    for r in top_results:
        page = r["metadata"].get("page", "?")
        source = r["metadata"].get("source", "")
        chunk_key = r.get("chunk_id") or (source, page, r["text"][:80])
        parts.append(f"[Página {page} | {source}]\n{r['text']}")
        if chunk_key not in seen_chunks:
            sources.append({
                "page": page,
                "source": source,
                "nivel_acesso": r["metadata"].get("nivel_acesso", "publico"),
                "matched_by": sorted(r["matched_by"]),
                "vector_score": r.get("vector_score", 0),
                "rerank_score": r.get("rerank_score", 0),
                "preview": r["text"][:130],
            })
            seen_chunks.add(chunk_key)

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
        "sources": requested_sources,
        "hybrid": True,
        "query_details": [
            {
                "operation": "aggregate / $vectorSearch",
                "namespace": f"{DB_NAME}.documents",
                "pipeline": [
                    {"$vectorSearch": {**vector_pipeline[0]["$vectorSearch"], "queryVector": f"<{len(embedding)} floats omitidos>"}},
                    *vector_pipeline[1:],
                ],
            },
            {
                "operation": "aggregate / $search",
                "namespace": f"{DB_NAME}.documents",
                "pipeline": lexical_pipeline,
            },
        ],
    }

    return "\n\n---\n\n".join(parts), sources, stats
