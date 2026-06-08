import os
import voyageai
from pymongo import MongoClient
from typing import Annotated, TypedDict, List
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_anthropic import ChatAnthropic
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.mongodb import MongoDBSaver
from config import DB_NAME, CLIENT_NAME, DOCUMENT_TITLE, SYSTEM_PROMPT_EXTRA
from dotenv import load_dotenv

load_dotenv()

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


def retrieve_context(query: str, top_k: int = 15) -> tuple[str, list[dict], dict]:
    history_keywords = ["pergunt", "anterior", "sessão", "conversa", "falei", "histórico"]
    if any(k in query.lower() for k in history_keywords):
        return "Responda com base no histórico da conversa.", [], {}

    voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
    client = MongoClient(os.environ["MONGO_URI"])
    collection = client[DB_NAME]["documents"]

    embedding = voyage.embed([query], model="voyage-3", input_type="query").embeddings[0]

    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": embedding,
                "numCandidates": top_k * 15,
                "limit": top_k,
            }
        },
        {
            "$project": {
                "text": 1,
                "metadata": 1,
                "vector_score": {"$meta": "vectorSearchScore"},
                "_id": 0,
            }
        },
    ]

    results = list(collection.aggregate(pipeline))
    client.close()

    if not results:
        return "Nenhum contexto encontrado.", [], {}

    documents = [r["text"] for r in results]
    try:
        rr = voyage.rerank(query, documents, model="rerank-2", top_k=8)
        reranked_indices = [item.index for item in rr.results]
        rerank_scores = {item.index: round(item.relevance_score, 4) for item in rr.results}
        top_results = [results[i] for i in reranked_indices]
        for i, r in enumerate(top_results):
            r["rerank_score"] = rerank_scores[reranked_indices[i]]
            r["vector_score"] = round(r.get("vector_score", 0), 4)
    except Exception:
        top_results = results[:8]
        for r in top_results:
            r["rerank_score"] = round(r.get("vector_score", 0), 4)
            r["vector_score"] = round(r.get("vector_score", 0), 4)

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
                "vector_score": r.get("vector_score", 0),
                "rerank_score": r.get("rerank_score", 0),
                "preview": r["text"][:130],
            })
            seen_pages.add(page)

    stats = {
        "num_candidates": top_k * 15,   # numCandidates do $vectorSearch
        "vector_hits": len(results),    # docs retornados pela busca vetorial
        "reranked": len(top_results),   # docs após rerank-2
        "index": "vector_index",
        "embed_model": "voyage-3",
        "rerank_model": "rerank-2",
        "embed_dim": len(embedding),
    }

    return "\n\n---\n\n".join(parts), sources, stats


llm = ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0)


def retrieve_node(state: AgentState) -> AgentState:
    query = state["messages"][-1].content
    context, sources, _ = retrieve_context(query)
    return {"context": context, "sources": sources}


def generate_node(state: AgentState) -> AgentState:
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="messages"),
    ])
    response = (prompt | llm).invoke({
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
    mongo_client = MongoClient(os.environ["MONGO_URI"])
    checkpointer = MongoDBSaver(mongo_client, db_name=DB_NAME)
    return builder.compile(checkpointer=checkpointer)
