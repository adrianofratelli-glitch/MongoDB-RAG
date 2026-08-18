# Assistente RAG Multi-tenant — prompt de construção

> Esse é o briefing que eu entrego **antes de existir uma linha de código**. Não é documentação do que existe: é o que eu daria pra alguém (ou pro Claude) subir a PoV inteira do zero.

Um assistente RAG sobre MongoDB Atlas Vector Search, com um deployment de referência sobre um documento público de planejamento de TI do setor público — e a stack **agnóstica de documento e de tenant**. Backend FastAPI em `:8180`, frontend Vite/React/LeafyGreen em `:5180`, um database por tenant (`rag_<CLIENT_ID>`).

O critério que define se a arquitetura ficou certa: **adicionar um tenant novo é `.env` + documento em `data/` + `client_config.json`. Zero mudança de código.**

| Arquivo | O que responde |
|---|---|
| [`docs/prompts/01-arquitetura.md`](docs/prompts/01-arquitetura.md) | o pipeline de 4 estágios e por que não é só `$vectorSearch`, multi-tenancy por env, controle de acesso, custo e limites, exposição da API, ordem de trabalho |
| [`docs/prompts/02-mongodb.md`](docs/prompts/02-mongodb.md) | coleções, os dois índices, ingestão e chunking, os pipelines vetorial e lexical, RRF, rerank, o `stats` do funil |
| [`docs/prompts/03-interface-fluxos.md`](docs/prompts/03-interface-fluxos.md) | componentes, `EngineStrip`, o SSE e a ordem dos eventos, roteiro de demo, nota de capturas |

Se for ler só um: o **02**, porque a qualidade da recuperação é o produto aqui. Fazer RAG qualquer um faz em uma tarde.
