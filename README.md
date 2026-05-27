# Enterprise RAG Assistant 🧠

Uma aplicação de inteligência artificial corporativa baseada em **RAG (Retrieval-Augmented Generation) avançado**, projetada para analisar, cruzar dados e responder perguntas complexas a partir de grandes volumes de documentos em PDF.

Este projeto serve como um *boilerplate* (modelo base) escalável, podendo ser adaptado para qualquer domínio de negócio (Jurídico, RH, Financeiro, Manuais Técnicos) que exija extração de dados com alta precisão.

## 🏗️ Arquitetura do Sistema

O fluxo de dados da aplicação segue o design pattern de agentes baseados em grafos de estado, garantindo rastreabilidade, velocidade via streaming e tratamento rigoroso do contexto:

```mermaid

graph TD

    User([👤 Usuário]) <-->|1. Chat / Prompt| ST[💻 Streamlit Frontend]

    ST <-->|2. Envia Mensagem / Atualiza UI| LG[🔗 LangGraph Agent Orchestrator]

    LG <-->|3. Persiste Sessão / Checkpoints| MG_DB[(🍃 MongoDB Atlas Database)]

    

    subgraph Pipeline RAG Avançado

        LG -->|4. Vetoriza Query| V_Emb[🔢 VoyageAI: voyage-3]

        V_Emb -->|5. Procura Chunks| MG_Search[🔍 MongoDB Vector Search]

        MG_Search -->|6. Retorna Candidatos| V_Rnk[🎯 VoyageAI: rerank-2]

        V_Rnk -->|7. Contexto Reordenado| LG

    end

    

    LG -->|8. Prompt + Contexto Limpo| Claude[🤖 Anthropic Claude 3.5 Sonnet]

    Claude -->|9. Token Streaming| ST