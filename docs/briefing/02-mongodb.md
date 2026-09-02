# Assistente RAG Multi-tenant — MongoDB: coleções, índices e recuperação

> Segunda parte do briefing. O que existe no Atlas, como é indexado, como é ingerido e exatamente quais pipelines rodam a cada pergunta.

---

## Um database por tenant

`rag_<CLIENT_ID>`. O `CLIENT_ID` do `.env` **nomeia o database** — é isso que faz "trocar de cliente" ser trocar variável de ambiente.

| Coleção | Papel |
|---|---|
| `documents` | os chunks: `text`, `embedding` (1024d), `metadata` (com `nivel_acesso`) |
| `conversations` | histórico por `thread_id`, com TTL |

### TTL nas conversas

```python
db["conversations"].create_index(
    "updated_at",
    name="updated_at_ttl",
    expireAfterSeconds=int(timedelta(days=CONVERSATION_RETENTION_DAYS).total_seconds()),
)
```

Default 30 dias, configurável. Dado de demo que fica pra sempre vira custo pra sempre.

### TTL nos uploads de demo

```python
db["documents"].create_index("metadata.expires_at", name="uploads_ttl", expireAfterSeconds=0)
```

Documento que sobe pela tela durante uma apresentação é descartável. Ele carimba `metadata.expires_at` (`UPLOAD_TTL_HOURS`, padrão 24) e some sozinho.

O truque que faz isso ser seguro: **o corpus ingerido pela CLI não recebe o campo**, e o varredor de TTL ignora documento onde o campo indexado não existe. Nada de flag `is_demo`, nada de job de limpeza, nada de filtro extra na busca — a ausência do campo já é a regra. Quem mexer nisso precisa saber: carimbar `expires_at` numa ingestão de corpus base apaga a demo de referência 24h depois, em silêncio.

Essa mesma ausência acabou virando a fronteira dos dois workspaces da tela: sem `expires_at` = corpus de referência do tenant, com `expires_at` = conteúdo enviado na demo. `documents.sources_for_scope(scope)` é literalmente um `distinct("metadata.source", {"metadata.expires_at": {"$exists": ...}})`, e o `/api/chat` usa o resultado como filtro de `metadata.source`. Duas abas isoladas sem banco novo, sem índice novo e sem campo novo.

## Os dois índices de busca — `setup_db.py`, idempotente

### `vector_index` (vectorSearch)

```python
{"fields": [
    {"type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine"},
    {"type": "filter", "path": "metadata.nivel_acesso"},
    {"type": "filter", "path": "metadata.source"},
]}
```

1024 dimensões porque o modelo é `voyage-3`. O campo `filter` **não é opcional** — é o que permite o controle de acesso rodar dentro do `$vectorSearch` em vez de depois. Quando o índice já existe, o script faz `update_search_index` justamente pra garantir que o filtro esteja lá; um índice antigo sem ele quebraria a garantia em silêncio.

### `text_index` (search, BM25)

```python
{"mappings": {"dynamic": False, "fields": {
    "text": {"type": "string"},
    "metadata": {"type": "document", "fields": {
        "nivel_acesso": {"type": "token"},
        "source": {"type": "token"},
    }},
}}}
```

`dynamic: False` de propósito — indexar campo que ninguém consulta é custo de índice sem retorno. `nivel_acesso` e `source` como `token` pra viabilizar o `compound.filter`.

Os dois índices são atualizados (`update_search_index`) mesmo quando já existem: um deploy antigo sem o campo `source` filtraria errado em silêncio.

## Ingestão

Um loader multi-formato: PDF, DOCX, TXT, CSV e HTML via loaders da comunidade LangChain, mais loaders leves próprios pra Markdown, JSON, XLSX (openpyxl) e PPTX (python-pptx).

Os loaders próprios existem pra **evitar a dependência pesada do `unstructured`**. Não adiciona ela — infla a imagem e traz uma árvore de dependências que não compensa por quatro formatos.

Chunking com `RecursiveCharacterTextSplitter`, **800 caracteres com 150 de overlap**.

Embedding em lotes pequenos, com **pausa de 22 segundos entre eles**: o tier gratuito da VoyageAI limita a 3 requisições por minuto. Deixa registrado que **isso é consequência do tier, não escolha de design** — senão daqui a seis meses alguém vai achar que a pausa tem uma razão arquitetural.

Cada chunk é etiquetado com `nivel_acesso` e com `source` (o nome do arquivo, normalizado). `source` é o eixo que separa documentos dentro do mesmo tenant: nada de banco novo por documento, nada de esperar build de índice na frente do cliente.

`ingest()` recebe `source_name` e `on_progress(phase, done, total)`. O CLI é um wrapper fino; o mesmo código roda por trás do upload da UI (`backend/documents.py`), em um executor de **um** worker — a cota da VoyageAI é o gargalo, então dois uploads paralelos só trocariam um job lento por dois travados.

```bash
python setup_db.py                                    # coleções + vector_index + text_index
python ingest.py caminho/documento.pdf
python ingest.py caminho/documento.pdf --reset        # reindexa documento existente
python ingest.py caminho/anexo.pdf --nivel restrito

# mesma esteira, pela API (o que a UI faz)
curl -X POST localhost:8180/api/documents -F "file=@documento.pdf" -F "reset=true"
curl localhost:8180/api/documents/jobs/<job_id>
curl -X DELETE localhost:8180/api/documents/<source>   # só uploads; corpus base = 403
```

## Conexão

Um **`MongoClient` único, singleton de módulo** (`db.py`), reusado em todo lugar pra aproveitar o pool. Ingestão e API reusam o mesmo.

**Nunca instancia `MongoClient` novo por requisição.** O `setup_db.py` abre o próprio, porque é script administrativo one-shot, e fecha na saída.

## O pipeline vetorial

```python
{"$vectorSearch": {
    "index": "vector_index",
    "path": "embedding",
    "queryVector": embedding,
    "numCandidates": top_k * 15,     # top_k default 15 → 225 candidatos
    "limit": top_k,
    "filter": {"metadata.nivel_acesso": {"$in": access_levels}},
}},
{"$project": {"text": 1, "metadata": 1, "vector_score": {"$meta": "vectorSearchScore"}}}
```

`numCandidates` em 15× o limite: HNSW precisa de folga pra não perder recall, e 15× é o que se mostrou suficiente nesse corpus sem virar latência.

## O pipeline lexical

```python
{"$search": {"index": "text_index", "compound": {
    "must":   [{"text": {"query": query, "path": "text"}}],
    "filter": [{"in": {"path": "metadata.nivel_acesso", "value": access_levels}}],
}}},
{"$limit": top_k},
{"$project": {"text": 1, "metadata": 1, "search_score": {"$meta": "searchScore"}}}
```

O ACL entra como `compound.filter`, dentro do `$search`. Mesmo princípio do lado vetorial: o filtro é do índice, não posterior.

## RRF

Funde por `_id`, `k = 60`:

```python
entry["rrf"] += 1.0 / (RRF_K + rank)
entry["matched_by"].add("vetorial" | "léxico")
```

O `matched_by` é o que alimenta o badge de motor de cada fonte na tela. Sem ele o híbrido é afirmação; com ele é evidência.

Fusão vazia → devolve "Nenhum contexto encontrado." em vez de alucinar sobre nada.

## Rerank

`voyage.rerank(query, documents, model="rerank-2", top_k=min(8, len(documents)))` sobre o conjunto fundido. Falhou, loga a exceção e **mantém a ordem do RRF**, copiando o score vetorial ou lexical disponível pro campo `rerank_score`. Uma API de terceiro fora do ar degrada a qualidade da resposta; não pode derrubar a resposta.

As fontes que a UI recebe são deduplicadas **por chunk** — a chave é o mesmo `_id` que a fusão usa. Já foi por `(source, page)`, e isso quebrou silenciosamente no corpus Markdown: sem paginação, todo chunk carrega `page: 0`, e as oito passagens reranqueadas viravam um único cartão de fonte. O painel de fontes é metade do argumento da demo; ele precisa mostrar os oito.

## O `stats` — o funil que a tela mostra

Cada resposta carrega o funil inteiro:

| Campo | O que é |
|---|---|
| `num_candidates` | `top_k * 15` — o que o `$vectorSearch` varreu |
| vindos da vetorial / da lexical | contribuição de cada motor |
| únicos após RRF | o tamanho do conjunto fundido |
| `reranked` | quantos sobraram depois do `rerank-2` |
| `rerank_model`, índices e modelos usados | procedência |

Número de funil é o que transforma o painel em prova em vez de enfeite.

## Conversas

Persistidas em `conversations`, retomáveis por `thread_id`.

Falha de persistência é **engolida de propósito**. Um soluço do banco não pode derrubar o chat: perder o histórico é aceitável, perder a conversa em andamento não é. Deixa isso comentado no código, porque parece descuido e não é.
