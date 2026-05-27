import streamlit as st
import uuid
import json
from datetime import datetime
from agent import build_graph, retrieve_context
from langchain_core.messages import HumanMessage
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from dotenv import load_dotenv
import os

load_dotenv()

st.set_page_config(
    page_title="PDTIC TJGO 2025/2027 — AI Assistant",
    page_icon="⚖️",
    layout="centered",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background-color: #001E2B; color: #FFFFFF; }
    .block-container { padding-top: 2rem; max-width: 820px; }
    [data-testid="stSidebar"] { background-color: #023430; border-right: 1px solid #00ED6430; }
    [data-testid="stSidebar"] * { color: #FFFFFF !important; }
    [data-testid="stChatMessage"] {
        background-color: #023430; border-radius: 12px;
        border: 1px solid #00ED6420; padding: 1rem; margin-bottom: 0.75rem;
    }
    [data-testid="stChatInput"] {
        background-color: #023430 !important; border: 1.5px solid #00ED64 !important;
        border-radius: 12px !important; color: #FFFFFF !important;
    }
    .stButton > button {
        background-color: transparent; border: 1px solid #00ED6460;
        border-radius: 8px; color: #00ED64 !important; font-size: 0.8rem;
        transition: all 0.2s; text-align: left; padding: 0.5rem 0.75rem;
    }
    .stButton > button:hover { background-color: #00ED6415; border-color: #00ED64; }
    .stTextInput input {
        background-color: #001E2B !important; color: #FFFFFF !important;
        border: 1px solid #00ED6460 !important; border-radius: 8px !important;
        font-size: 0.8rem !important;
    }
    .source-card {
        background: #001E2B; border: 1px solid #00ED6430; border-radius: 8px;
        padding: 10px 12px; margin: 4px 0; font-size: 0.8rem;
    }
    .source-page { color: #00ED64; font-weight: 600; font-size: 0.75rem; }
    .source-score { color: #889397; font-size: 0.7rem; }
    .source-preview { color: #CCCCCC; margin-top: 3px; line-height: 1.4; }
    .followup-btn { margin: 3px 0; }
    .session-box {
        background-color: #001E2B; border: 2px solid #00ED64;
        border-radius: 10px; padding: 12px 14px; margin: 6px 0 10px 0;
    }
    .session-label { color: #00ED64; font-size: 0.68rem; font-weight: 700;
        text-transform: uppercase; letter-spacing: 1.2px; margin-bottom: 5px; }
    .session-id { color: #FFFFFF; font-family: 'Courier New', monospace;
        font-size: 0.82rem; word-break: break-all; line-height: 1.5; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 20px; font-size: 0.7rem; font-weight: 600; }
    .badge-new { background: #00ED6420; color: #00ED64; border: 1px solid #00ED6440; }
    .badge-resumed { background: #FFA50020; color: #FFA500; border: 1px solid #FFA50040; }
    .metric-card {
        background: #001E2B; border: 1px solid #00ED6430; border-radius: 8px;
        padding: 8px 12px; text-align: center; margin: 4px 0;
    }
    .metric-value { color: #00ED64; font-size: 1.1rem; font-weight: 700; }
    .metric-label { color: #889397; font-size: 0.7rem; margin-top: 2px; }
    hr { border-color: #00ED6420; }
    #MainMenu {visibility:hidden;} footer {visibility:hidden;} header {visibility:hidden;}
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="display:flex; align-items:center; gap:16px; margin-bottom:8px;">
    <svg width="48" height="48" viewBox="0 0 256 549" xmlns="http://www.w3.org/2000/svg">
        <path d="M177.3 51.3C152.7 22.6 130.9 0 128.4 0c-2.6 0-24.3 22.6-48.9 51.3C30.7 108.8 0 178.9 0 235.6c0 68.5 57.4 124.1 128 124.1s128-55.6 128-124.1c0-56.7-30.7-126.8-78.7-184.3zM128 332.9v182.8s-73.8-105.3-73.8-280c0 0 10.3 77.5 73.8 97.2z" fill="#00ED64"/>
    </svg>
    <div>
        <h1 style="margin:0; color:#FFFFFF; font-size:1.6rem; font-weight:700;">Assistente PDTIC TJGO</h1>
        <p style="margin:0; color:#00ED64; font-size:0.85rem; font-weight:500;">
            2025/2027 · Powered by MongoDB Atlas Vector Search
        </p>
    </div>
</div>
<p style="color:#889397; font-size:0.9rem; margin-bottom:1.5rem;">
    Converse com o Plano Diretor de Tecnologia da Informação e Comunicação 
    do Tribunal de Justiça do Estado de Goiás.
</p>
<hr style="margin-bottom:1.5rem;">
""", unsafe_allow_html=True)

# ── Session State ─────────────────────────────────────────────────────────────
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "sources_history" not in st.session_state:
    st.session_state.sources_history = []
if "session_type" not in st.session_state:
    st.session_state.session_type = "new"
if "total_queries" not in st.session_state:
    st.session_state.total_queries = 0
if "graph" not in st.session_state:
    with st.spinner("⚙️ Iniciando agente com MongoDB Atlas..."):
        st.session_state.graph = build_graph()

# ── Histórico ─────────────────────────────────────────────────────────────────
if not st.session_state.messages:
    with st.chat_message("assistant"):
        st.markdown(
            "Olá! Sou o assistente de IA especializado no **PDTIC 2025/2027 do TJGO**. "
            "Estou conectado ao MongoDB Atlas para cruzar dados e responder perguntas sobre o nosso planejamento estratégico, cronogramas e orçamentos. Como posso ajudar hoje?"
        )

for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        # Mostra citações das respostas anteriores
        if msg["role"] == "assistant" and i // 2 < sum(len(s) for s in st.session_state.sources_history):
            src_idx = i // 2
            if src_idx < sum(len(s) for s in st.session_state.sources_history):
                sources = st.session_state.sources_history[src_idx]
                if sources:
                    with st.expander(f"📎 {len(sources)} fonte(s) consultada(s)", expanded=False):
                        for s in sources:
                            score_pct = int(s['rerank_score'] * 100)
                            bar = "█" * (score_pct // 10) + "░" * (10 - score_pct // 10)
                            st.markdown(
                                f"""<div class="source-card">
                                    <span class="source-page">📄 Página {s['page']}</span>
                                    <span class="source-score"> · {bar} {score_pct}%</span>
                                    <div class="source-preview">{s['preview']}...</div>
                                </div>""",
                                unsafe_allow_html=True
                            )

# ── Sugestões iniciais ────────────────────────────────────────────────────────
QUESTIONS = [
    "📈 Qual foi a evolução do iGovTIC-JUD de 2021 a 2024?",
    "🤖 Quais são as iniciativas de IA previstas no PDTIC?",
    "💰 Quais as ações com maior custo e investimento total?",
    "🏗️ O que está planejado para o datacenter do TJGO?",
    "🔐 Quais são as ações de segurança da informação?",
    "📱 Quais aplicativos móveis estão previstos?",
    "☁️ Há previsão de migração para nuvem? Qual o plano?",
    "🎯 Quais são os OKRs e metas do PDTIC 2025/2027?",
]

if not st.session_state.messages:
    st.markdown(
        "<p style='color:#889397; font-size:0.85rem; margin-bottom:0.5rem;'>"
        "💡 Sugestões baseadas no conteúdo do PDTIC</p>",
        unsafe_allow_html=True
    )
    cols = st.columns(2)
    for i, q in enumerate(QUESTIONS):
        if cols[i % 2].button(q, key=f"q{i}", use_container_width=True):
            st.session_state.pending = q
            st.rerun()
    st.markdown("<br>", unsafe_allow_html=True)

# ── Follow-up suggestions ─────────────────────────────────────────────────────
FOLLOWUPS = {
    "igovtic": ["Como o TJGO pode melhorar ainda mais o iGovTIC?", "Quais dimensões tiveram menor pontuação?"],
    "ia": ["Qual o cronograma das iniciativas de IA?", "Quais sistemas serão integrados com IA?"],
    "custo": ["Como é feito o monitoramento orçamentário?", "Quais ações têm maior ROI esperado?"],
    "datacenter": ["Qual o custo previsto para o datacenter?", "Quando está prevista a entrega?"],
    "segurança": ["O que é o plano de ação ENSEC-PJ?", "Como funciona o SIEM no TJGO?"],
    "cloud": ["Qual provedor de nuvem está previsto?", "Quais sistemas migrarão para nuvem?"],
    "okr": ["Como os OKRs são monitorados?", "Qual a frequência de revisão do PDTIC?"],
}

def get_followups(query: str) -> list:
    q = query.lower()
    for key, suggestions in FOLLOWUPS.items():
        if key in q or any(w in q for w in key.split()):
            return suggestions
    return ["📋 Quais são as próximas ações planejadas?", "🗓️ Qual o cronograma de implementação?"]

# ── Input ─────────────────────────────────────────────────────────────────────
user_input = st.chat_input("Faça uma pergunta sobre o PDTIC TJGO 2025/2027...")

if "pending" in st.session_state:
    user_input = st.session_state.pop("pending")

# ── Invoke com streaming ──────────────────────────────────────────────────────
if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    st.session_state.total_queries += 1

    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        # Retrieve context first
        with st.spinner("🔍 Buscando no PDTIC..."):
            context, sources = retrieve_context(user_input)

        # Streaming
        llm_stream = ChatAnthropic(
            model="claude-sonnet-4-20250514",
            temperature=0,
            streaming=True,
            api_key=os.environ["ANTHROPIC_API_KEY"]
        )

        SYSTEM = """Você é um assistente especializado no PDTIC 2025/2027 do TJGO.
Responda usando APENAS o contexto fornecido. Use linguagem formal e objetiva.
Se a informação não estiver no contexto, diga claramente.

REGRAS DE FORMATAÇÃO:
- Coloque em **negrito** valores financeiros (ex: **R$ 40.000.000,00**), datas/prazos (ex: **DEZ./2026**) e códigos de ação (ex: **AC 09**).
- Use listas (bullet points) ao citar mais de dois itens.
- Formate a resposta em uma tabela Markdown se o usuário perguntar sobre múltiplas ações cruzando custos ou cronogramas.

Ao final, adicione: 📎 **Fontes:** [páginas consultadas]

CONTEXTO:
{context}"""

        # Monta histórico para o streaming
        history_msgs = []
        for m in st.session_state.messages[:-1]:
            if m["role"] == "user":
                history_msgs.append(HumanMessage(content=m["content"]))

        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM.format(context=context)),
            *[(("human" if m["role"] == "user" else "ai"), m["content"])
              for m in st.session_state.messages[:-1]],
            ("human", user_input)
        ])

        full_response = ""
        placeholder = st.empty()

        with st.spinner(""):
            for chunk in llm_stream.stream(
                prompt.format_messages(context=context)
            ):
                full_response += chunk.content
                placeholder.markdown(full_response + "▌")

        placeholder.markdown(full_response)

        # Salva também no LangGraph checkpointer
        config = {"configurable": {"thread_id": st.session_state.thread_id}}
        st.session_state.graph.invoke(
            {"messages": [HumanMessage(content=user_input)]},
            config=config
        )

        # Mostra citações
        st.session_state.sources_history.append(sources)
        if sources:
            with st.expander(f"📎 {len(sources)} fonte(s) consultada(s) — clique para ver", expanded=False):
                for s in sources:
                    score_pct = int(s['rerank_score'] * 100)
                    bar = "█" * (score_pct // 10) + "░" * (10 - score_pct // 10)
                    st.markdown(
                        f"""<div class="source-card">
                            <span class="source-page">📄 Página {s['page']}</span>
                            <span class="source-score"> · {bar} {score_pct}%</span>
                            <div class="source-preview">{s['preview']}...</div>
                        </div>""",
                        unsafe_allow_html=True
                    )

        # Follow-up suggestions
        followups = get_followups(user_input)
        st.markdown(
            "<p style='color:#889397; font-size:0.78rem; margin:12px 0 4px 0;'>"
            "💬 Perguntas relacionadas:</p>",
            unsafe_allow_html=True
        )
        fcols = st.columns(2)
        for i, fq in enumerate(followups[:2]):
            if fcols[i].button(fq, key=f"f{st.session_state.total_queries}_{i}",
                               use_container_width=True):
                st.session_state.pending = fq
                st.rerun()

    st.session_state.messages.append({"role": "assistant", "content": full_response})

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="text-align:center; padding:1rem 0 0.5rem 0;">
        <svg width="36" height="36" viewBox="0 0 256 549" xmlns="http://www.w3.org/2000/svg">
            <path d="M177.3 51.3C152.7 22.6 130.9 0 128.4 0c-2.6 0-24.3 22.6-48.9 51.3C30.7 108.8 0 178.9 0 235.6c0 68.5 57.4 124.1 128 124.1s128-55.6 128-124.1c0-56.7-30.7-126.8-78.7-184.3zM128 332.9v182.8s-73.8-105.3-73.8-280c0 0 10.3 77.5 73.8 97.2z" fill="#00ED64"/>
        </svg>
        <p style="color:#00ED64; font-weight:600; margin:6px 0 0 0;">MongoDB Atlas</p>
        <p style="color:#889397; font-size:0.72rem; margin:2px 0;">Vector Search · RAG · Checkpointer</p>
    </div>
    <hr style="border-color:#00ED6430; margin:0.75rem 0;">
    """, unsafe_allow_html=True)

    # Métricas da sessão
    st.markdown("**📊 Sessão Atual**")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            f"<div class='metric-card'><div class='metric-value'>{st.session_state.total_queries}</div>"
            f"<div class='metric-label'>Perguntas</div></div>",
            unsafe_allow_html=True
        )
    with c2:
        st.markdown(
            f"<div class='metric-card'><div class='metric-value'>{sum(len(s) for s in st.session_state.sources_history)}</div>"
            f"<div class='metric-label'>Chunks Lidos</div></div>",
            unsafe_allow_html=True
        )

    st.markdown("<hr style='border-color:#00ED6430; margin:0.75rem 0;'>", unsafe_allow_html=True)

    # Session ID
    badge = (
        '<span class="badge badge-resumed">▶ Retomada</span>'
        if st.session_state.session_type == "resumed"
        else '<span class="badge badge-new">✦ Nova</span>'
    )
    st.markdown(f"**🔑 Session ID** &nbsp;{badge}", unsafe_allow_html=True)
    st.markdown(
        f"""<div class="session-box">
            <div class="session-label">Thread ID — MongoDB checkpoints</div>
            <div class="session-id">{st.session_state.thread_id}</div>
        </div>""",
        unsafe_allow_html=True
    )
    st.code(st.session_state.thread_id, language=None)

    # Retomar sessão
    st.markdown(
        "<p style='color:#889397; font-size:0.75rem; margin:4px 0 6px 0;'>"
        "Retomar conversa anterior:</p>",
        unsafe_allow_html=True
    )
    resume_input = st.text_input(
        "Thread ID",
        placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        label_visibility="collapsed"
    )
    if st.button("▶ Retomar Sessão", use_container_width=True):
        if resume_input and len(resume_input) > 10:
            st.session_state.thread_id = resume_input.strip()
            st.session_state.messages = []
            st.session_state.sources_history = []
            st.session_state.session_type = "resumed"
            st.session_state.total_queries = 0
            st.success("✅ Sessão retomada!")
            st.rerun()
        else:
            st.error("Thread ID inválido.")

    st.markdown("<hr style='border-color:#00ED6430; margin:0.75rem 0;'>", unsafe_allow_html=True)

    # Export
    st.markdown("**💾 Exportar Conversa**")
    if st.session_state.messages:
        # TXT
        export_txt = f"PDTIC TJGO 2025/2027 — Conversa exportada\n"
        export_txt += f"Session ID: {st.session_state.thread_id}\n"
        export_txt += f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
        export_txt += "=" * 60 + "\n\n"
        for m in st.session_state.messages:
            role = "Usuário" if m["role"] == "user" else "Assistente"
            export_txt += f"[{role}]\n{m['content']}\n\n"

        st.download_button(
            "📄 Baixar como TXT",
            data=export_txt,
            file_name=f"pdtic_tjgo_{st.session_state.thread_id[:8]}.txt",
            mime="text/plain",
            use_container_width=True
        )

        # JSON
        export_json = json.dumps({
            "session_id": st.session_state.thread_id,
            "exported_at": datetime.now().isoformat(),
            "document": "PDTIC TJGO 2025/2027",
            "messages": st.session_state.messages
        }, ensure_ascii=False, indent=2)

        st.download_button(
            "📦 Baixar como JSON",
            data=export_json,
            file_name=f"pdtic_tjgo_{st.session_state.thread_id[:8]}.json",
            mime="application/json",
            use_container_width=True
        )
    else:
        st.markdown(
            "<p style='color:#889397; font-size:0.78rem;'>Inicie uma conversa para exportar.</p>",
            unsafe_allow_html=True
        )

    st.markdown("<hr style='border-color:#00ED6430; margin:0.75rem 0;'>", unsafe_allow_html=True)

    # Documento e Stack
    st.markdown("**📄 Documento**")
    st.markdown(
        "<p style='font-size:0.82rem; color:#889397;'>"
        "PDTIC TJGO 2025/2027<br>88 páginas · 210 chunks<br>"
        "Tribunal de Justiça de Goiás</p>",
        unsafe_allow_html=True
    )

    st.markdown("<hr style='border-color:#00ED6430; margin:0.75rem 0;'>", unsafe_allow_html=True)
    st.markdown("**🛠️ Stack**")
    for icon, name, desc in [
        ("🍃", "MongoDB Atlas", "Vector Search + Persistence"),
        ("🔢", "VoyageAI", "voyage-3 Embeddings"),
        ("🔗", "LangGraph", "Agent + Checkpointer"),
        ("🤖", "Claude Sonnet", "LLM Generation"),
    ]:
        st.markdown(
            f"<div style='margin-bottom:6px;'>"
            f"<span style='color:#00ED64; font-size:0.85rem;'>{icon} {name}</span>"
            f"<br><span style='color:#889397; font-size:0.72rem;'>{desc}</span>"
            f"</div>",
            unsafe_allow_html=True
        )

    st.markdown("<hr style='border-color:#00ED6430; margin:0.75rem 0;'>", unsafe_allow_html=True)

    if st.button("🔄 Nova Conversa", use_container_width=True):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.sources_history = []
        st.session_state.session_type = "new"
        st.session_state.total_queries = 0
        st.rerun()
