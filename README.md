# Assistente PDTIC TJGO 2025/2027 ⚖️

Uma aplicação de inteligência artificial baseada na arquitetura **RAG (Retrieval-Augmented Generation)** para interagir com o Plano Diretor de Tecnologia da Informação e Comunicação do Tribunal de Justiça do Estado de Goiás.

## 🛠️ Stack Tecnológica
- **Interface:** Streamlit
- **Banco de Dados/Vector Search:** MongoDB Atlas
- **Embeddings & Reranker:** VoyageAI (`voyage-3` e `rerank-2`)
- **LLM:** Anthropic Claude 3.5 Sonnet
- **Agente e Memória:** LangGraph

## 🚀 Como rodar localmente
1. Clone o repositório.
2. Crie um ambiente virtual: `python3 -m venv .venv` e ative-o com `source .venv/bin/activate`.
3. Instale as dependências: `pip install -r requirements.txt`.
4. Crie um arquivo `.env` na raiz do projeto com as chaves:
   - `MONGO_URI`
   - `VOYAGE_API_KEY`
   - `ANTHROPIC_API_KEY`
5. Rode o comando: `streamlit run app.py`
