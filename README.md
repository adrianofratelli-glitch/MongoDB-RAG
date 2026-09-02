# Assistente RAG — MongoDB Atlas Vector Search

Faça uma pergunta em linguagem natural a um documento de planejamento de 200 páginas e receba uma resposta com citações em segundos. Busca vetorial e lexical rodam em paralelo no Atlas, o RRF funde os ranqueamentos, um re-ranker escolhe as melhores passagens, e o Claude responde usando só elas — em streaming, token a token.

Agnóstico de tenant por design: nenhum nome de cliente, documento ou marca vive no repositório. Um novo tenant é um `.env`, um PDF e um arquivo JSON. E, na própria tela, dá para enviar um documento novo e conversar com ele em seguida — a mesma esteira de ingestão, sem tocar em linha de comando, em uma aba separada que nunca se mistura com o corpus de referência.

## A demo em 5 passos

**1. Escolha a aba, um perfil de acesso e uma pergunta.** A aba **Corpus de referência** conversa com o documento do tenant; **Novo conteúdo** é o espaço do que for enviado na hora. O perfil (público / restrito) é o filtro de ACL aplicado às *duas* etapas de busca, com negação por padrão.

![Tela inicial com as duas abas de workspace, o seletor de perfil de acesso e as perguntas iniciais](docs/screenshots/01-home.png)

**2. Pergunte.** A consulta vira embedding com o `voyage-3` e roda `$vectorSearch` e Atlas Search (BM25) em paralelo, cada um já filtrado por nível de acesso.

**3. Veja o pipeline se explicar.** O RRF funde os dois ranqueamentos, o `rerank-2` reordena, os 8 melhores chunks viram o contexto — e a UI mostra qual etapa produziu o quê.

![Resposta chegando em streaming com o pipeline de recuperação mostrado etapa por etapa](docs/screenshots/02-answer.png)

**4. Confira as fontes.** Toda resposta carrega as passagens de onde veio — um cartão por chunk reranqueado, com o badge do motor que o trouxe (`VETORIAL`, `LÉXICO` ou os dois) e os scores `vetorial → rerank`. Dá para verificar em vez de confiar.

![Painel de fontes expandido: um cartão por chunk, com os badges VETORIAL/LÉXICO e os scores vetorial → rerank](docs/screenshots/03-sources.png)

**5. Envie um documento na hora, em uma aba separada.** A tela tem dois espaços: **Corpus de referência** (o documento do tenant, só leitura) e **Novo conteúdo**. Na segunda aba, arraste um arquivo: ele é fatiado, embedado com `voyage-3` e indexado no mesmo banco do tenant, com barra de progresso. Cada aba tem conversa própria e só recupera os próprios documentos — o `/api/chat` resolve esse escopo no servidor, então uma resposta nunca mistura os dois corpora. Os dois filtros de busca ganham `metadata.source` junto com o nível de acesso. Conteúdo enviado assim é descartável: expira sozinho em 24h por um índice TTL, e é essa marca de TTL que separa as duas abas — sem banco novo, sem índice novo.

![Aba Novo conteúdo: painel de upload aberto, o documento enviado com o prazo de expiração e a resposta gerada só a partir dele](docs/screenshots/04-upload.png)

> Os screenshots rodam contra um tenant real; os nomes de organização, documento, banco e identificadores citados nas respostas foram substituídos por nomes neutros no DOM antes da captura.

## Como uma pergunta é respondida

```mermaid
graph TD
    User([User]) <-->|Chat / SSE| UI[React + LeafyGreen]
    UI <-->|HTTP /api| API[FastAPI]
    API -->|query| EMB[voyage-3 embedding]
    EMB --> VS[Atlas Vector Search + ACL filter]
    API --> LX[Atlas Search BM25 + ACL filter]
    VS --> RRF[Reciprocal Rank Fusion]
    LX --> RRF
    RRF --> RNK[rerank-2]
    RNK --> LLM[Claude Sonnet 4.6]
    LLM -->|token streaming| API
    API <-->|conversation| MDB[(Atlas · conversations)]
```

Se um dos dois índices falhar, o outro sustenta a consulta. O bloco estável de instruções (incluindo um sumário do documento) fica em cache na API da Anthropic, então turnos repetidos custam menos. As conversas são persistidas no MongoDB e retomadas pelo thread ID.

A ingestão aceita PDF, DOCX, TXT, CSV, Markdown, HTML, JSON, XLSX e PPTX — pela CLI (`ingest.py`) ou pelo upload na UI, que enfileira um job e devolve o progresso em `/api/documents/jobs/{job_id}`. Os documentos convivem na mesma coleção, separados por `metadata.source`, que é campo de filtro nos dois índices de busca.

> Prova de conceito: o nível de acesso é escolhido na UI para fins de demonstração. Em produção viria da autenticação (SSO / JWT), nunca do cliente.

## Como rodar

```bash
python3 -m venv .venv && source .venv/bin/activate
# Setup/ingestão multiformato (inclui as dependências enxutas da API)
pip install -r requirements-ingest.txt
cp .env.example .env          # chaves + valores do tenant
python setup_db.py            # coleções + vector_index + text_index
python ingest.py data/document.pdf
cp client_config.example.json client_config.json   # perguntas iniciais (opcional)
./run.sh                      # backend :8180, frontend :5180
```

Por padrão, o launcher serve o build otimizado do frontend sem watcher. Para editar com HMR, rode `POV_DEV=1 ./run.sh`; o build só é refeito quando fontes, lockfile ou configuração mudam.

```env
MONGO_URI=
VOYAGE_API_KEY=
ANTHROPIC_API_KEY=
CLIENT_ID=tenant_id           # o banco vira rag_<CLIENT_ID>
CLIENT_NAME=Tenant Name
DOCUMENT_TITLE=Document Title
DOCUMENT_DESCRIPTION=Exibido no cabeçalho
```

Os índices de busca do Atlas levam cerca de um minuto para ficarem consultáveis. Ingira conteúdo restrito com `--nivel restrito`, reindexe com `--reset`. O tier gratuito da VoyageAI permite 3 requisições por minuto, então a ingestão gera embeddings em lotes pequenos com uma pausa (`VOYAGE_SLEEP_S`) e insere cada lote conforme avança, para que uma interrupção não perca o progresso.

Opcionais: `DB_NAME`, `SYSTEM_PROMPT_EXTRA`, `ALLOWED_ORIGINS`, `MAX_UPLOAD_MB` (padrão 25), `UPLOAD_DIR` (padrão `data/uploads`), `UPLOAD_TTL_HOURS` (padrão 24; `0` torna o upload permanente).

O TTL marca `metadata.expires_at` **só** nos chunks enviados pela UI. O corpus ingerido pela CLI não recebe o campo, e o varredor de TTL do MongoDB ignora documentos onde o campo indexado não existe — então o documento de referência do tenant nunca expira. O arquivo enviado também é apagado do disco assim que os vetores chegam ao Atlas. Para ingerir pela CLI com prazo, use `--ttl-horas 24`.

Uploads rodam em um único worker: a mesma cota da VoyageAI limita a ingestão, então jobs enfileiram em vez de competir. Um documento grande leva minutos no tier gratuito — em demo ao vivo, prefira arquivos pequenos ou uma chave paga com `VOYAGE_SLEEP_S` baixo.

Testes: `python -m unittest discover -s tests -v` — lógica pura, sem serviços ao vivo.

## Fronteira de produção

Histórico do chat, tamanho do sumário, tokens de saída e streams RAG concorrentes são limitados; a imagem roda como UID 10001 atrás do nginx com cabeçalhos de segurança. O filtro por nível de acesso é aplicado nos dois caminhos de recuperação, mas o nível selecionado ainda vem do cliente nesta PoV. O upload valida extensão, tamanho e nome do arquivo, mas — como todo endpoint aqui — não exige autenticação: quem alcança a API indexa ou remove documentos do tenant. Uma implantação externa exige tenant e claims de ACL derivados de SSO/JWT; nunca confie no `access_level` vindo da requisição.

## Adicionando um tenant

Defina os valores do tenant no `.env`, coloque o documento em `data/`, customize o `client_config.json` e então rode `setup_db.py` → `ingest.py` → `run.sh`. Cada tenant ganha o próprio banco (`rag_<CLIENT_ID>`). `data/`, `assets/` e `client_config.json` estão no gitignore — nada específico de tenant chega ao repositório.

## Organização

```
backend/api.py     app FastAPI (config / status / chat SSE / métricas)
frontend/          React + Vite + LeafyGreen
agent.py           busca híbrida + RRF + rerank, com ACL
ingest.py          ingestão multiformato (--nivel define o nível de acesso)
backend/documents.py  biblioteca de documentos: upload, jobs de ingestão, remoção de uploads
setup_db.py        coleções e os dois índices de busca
config.py db.py    configuração e cliente Mongo compartilhado
observability.py   logging estruturado + /api/metrics
```

## Stack

React + Vite + LeafyGreen · FastAPI (SSE) · MongoDB Atlas Vector Search + Atlas Search · VoyageAI `voyage-3` / `rerank-2` · Claude Sonnet 4.6 · loaders da comunidade LangChain.
