import os
import time
import voyageai
from pymongo import MongoClient
from typing import Annotated, TypedDict, List
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_anthropic import ChatAnthropic
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.mongodb import MongoDBSaver
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """Você é um assistente especializado no PDTIC 2025/2027 do TJGO.

Você tem dois tipos de informação:
1. CONTEXTO DO PDTIC: trechos mais relevantes, já reordenados por relevância
2. HISTÓRICO: perguntas e respostas desta sessão

Regras rigorosas de comportamento e formatação:
- Responda usando APENAS o contexto fornecido. Se não encontrar, diga claramente.
- Para perguntas sobre histórico, use as mensagens anteriores.
- DESTAQUE VISUAL: Sempre coloque em **negrito** valores financeiros (ex: **R$ 40.000.000,00**), datas/prazos (ex: **DEZ./2026**) e códigos de ação (ex: **AC 09**, **AG 01**).
- ESTRUTURA: Use listas (bullet points) sempre que citar mais de dois itens. 
- TABELAS: Se o usuário perguntar sobre múltiplas ações, custos ou cronogramas, formate a resposta obrigatoriamente em uma tabela Markdown.

CONTEXTO DO PDTIC:
{context}"""

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    context: str
    sources: List[dict]

def retrieve_context(query: str, top_k: int = 15) -> tuple:
    history_keywords = ["pergunt", "anterior", "sessão", "conversa", "falei", "histórico"]
    if any(k in query.lower() for k in history_keywords):
        return "Responda com base no histórico da conversa.", []

    voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
    client = MongoClient(os.environ["MONGO_URI"])
    collection = client["tjgo_pdtic"]["documents"]

    # 1. Vector Search — busca candidatos
    embedding = voyage.embed(
        [query], model="voyage-3", input_type="query"
    ).embeddings[0]

    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": embedding,
                "numCandidates": top_k * 15,
                "limit": top_k
            }
        },
        {
            "$project": {
                "text": 1,
                "metadata": 1,
                "vector_score": {"$meta": "vectorSearchScore"},
                "_id": 0
            }
        }
    ]

    results = list(collection.aggregate(pipeline))
    client.close()

    if not results:
        return "Nenhum contexto encontrado.", []

    # 2. Reranker — reordena por relevância semântica real
    documents = [r["text"] for r in results]
    reranked = []
    try:
        rr = voyage.rerank(query, documents, model="rerank-2", top_k=8)
        reranked_indices = [item.index for item in rr.results]
        rerank_scores = {item.index: round(item.relevance_score, 4) for item in rr.results}
        top_results = [results[i] for i in reranked_indices]
        for i, r in enumerate(top_results):
            r["rerank_score"] = rerank_scores[reranked_indices[i]]
            r["vector_score"] = round(r.get("vector_score", 0), 4)
    except Exception as e:
        # Fallback sem reranker
        top_results = results[:8]
        for r in top_results:
            r["rerank_score"] = round(r.get("vector_score", 0), 4)
            r["vector_score"] = round(r.get("vector_score", 0), 4)

    # Monta contexto e sources
    parts = []
    sources = []
    seen_pages = set()

    for r in top_results:
        page = r["metadata"].get("page", "?")
        parts.append(f"[Página {page}]\n{r['text']}")
        if page not in seen_pages:
            sources.append({
                "page": page,
                "vector_score": r.get("vector_score", 0),
                "rerank_score": r.get("rerank_score", 0),
                "preview": r["text"][:130]
            })
            seen_pages.add(page)

    return "\n\n---\n\n".join(parts), sources

llm = ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0)

def retrieve_node(state: AgentState) -> AgentState:
    query = state["messages"][-1].content
    context, sources = retrieve_context(query)
    return {"context": context, "sources": sources}

def generate_node(state: AgentState) -> AgentState:
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="messages"),
    ])
    response = (prompt | llm).invoke({
        "context": state["context"],
        "messages": state["messages"]
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
    checkpointer = MongoDBSaver(mongo_client, db_name="tjgo_pdtic")
    return builder.compile(checkpointer=checkpointer)
