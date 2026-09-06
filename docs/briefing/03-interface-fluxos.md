# Assistente RAG Multi-tenant — interface, fluxos e roteiro

> Terceira parte do briefing. A tela, o streaming, e o roteiro que fecha a conversa comercial.

---
## Estado atual — modo palco

É uma única conversa, sem sidebar. Escopo público/restrito, conexão e nova
conversa ficam na barra superior; a área central mostra pergunta, streaming,
fontes e evidência de recuperação. Histórico e métricas globais não ocupam o
primeiro viewport.

## Contrato visual do portfólio (v2)

Esta UI participa da assinatura MongoDB Dark das PoVs. O arquivo
`src/pov-signature.css` é uma cópia sincronizada entre os onze frontends e deve
ser importado **depois** do stylesheet local. O contêiner raiz carrega
`data-pov-shell`, existe um `.pov-skip-link` para `#conteudo-principal` e o
`index.html` declara pt-BR, dark color scheme, theme color e o favicon comum.

A camada compartilhada é dona da document rail, foco, touch targets e redução de
movimento. Este arquivo continua dono do fluxo e das exceções de domínio: não
achate uma tela operacional num template de landing page e não remova a tese
visual específica desta PoV. Qualquer mudança na assinatura precisa ser
replicada nas onze cópias e validada em 1440, 768 e 360 px, além do build de
produção e do estado offline.


## O papel da tela

O ponto do PoC é o pipeline de recuperação. Mas ninguém aprova um pipeline olhando log: a tela é onde o híbrido, o rerank e o controle de acesso viram argumento.

Regra: **a UI não decide nada de recuperação.** Ela mostra o que o backend já resolveu.

## Stack

| Item | Escolha | Motivo |
|---|---|---|
| Build | Vite, porta `5180` com `strictPort` | 5173 já está ocupada por outras PoVs nesta máquina; falhar alto é melhor que trocar de porta em silêncio |
| UI kit | LeafyGreen | design system do MongoDB — a demo já parece produto Atlas, sem eu desenhar nada |
| Estado | `useState` no `App.jsx` (casca) e no `WorkspaceView` (cada aba) | poucos estados e dois componentes de orquestração. Não justifica biblioteca |
| HTTP | `axios` nos GETs, `fetch` cru no chat | o streaming precisa de `ReadableStream`, que o axios não entrega no browser |
| Markdown | `react-markdown` + `remark-gfm` | a resposta vem em markdown com tabela e lista |

Um detalhe que já me custou tempo: `@leafygreen-ui/emotion` importa `@emotion/server` (extração de CSS crítico no SSR), que quebra no browser. Resolve com um alias no `vite.config.js` apontando pra um stub vazio — o caminho de SSR nunca é chamado em runtime.

O dev server proxia `/api` pro backend em `:8180`. Em Docker quem faz esse papel é o nginx, mesma origem, sem CORS.

## Componentes

Sem router. Uma tela só, porque a demo é uma conversa — dividida em **duas abas** que
não se misturam: `Corpus de referência` (o documento do tenant, só leitura) e
`Novo conteúdo` (o que for enviado durante a demo).

| Componente | Papel |
|---|---|
| `EngineStrip` | **a peça central.** Mostra o que cada motor contribuiu: lexical, vetorial, rerank |
| `Sources` | os chunks que fundamentaram a resposta, com badge de qual motor os trouxe e os scores `vetorial → rerank` |
| `ChatMessage` | renderiza markdown; a resposta chega token a token |
| `ChatInput` | entrada, com o envio bloqueado enquanto um turno está em andamento |
| `TopBar` | `access_level`, status do banco, nova conversa e reconexão |
| `OfflineHero` | tela quando o Atlas não responde, com o nome do banco e o botão de reconectar |
| `Welcome` | perguntas prontas pra clicar. **Ninguém digita durante apresentação** |
| `WorkspaceView` | um espaço de trabalho isolado: thread, mensagens, documentos marcados e `scope` próprios. As duas abas montam um cada, e **as duas ficam montadas** — trocar de aba não pode matar um stream em curso nem apagar a conversa da outra. "Nova conversa" remonta só a aba ativa |
| `DocumentsPanel` | biblioteca daquela aba (`workspace` = `base` ou `uploads`): arrasta um arquivo e ele entra na esteira, com progresso por chunk; marca quais documentos a recuperação enxerga. **Não remove nada** — o corpus base é o chão da demo e reingeri-lo custa uma hora de embedding com rate limit, então a tela não oferece esse botão; uploads somem sozinhos pelo TTL |

A separação entre as abas não é cosmética e **não é o frontend que a garante**: o
`/api/chat` recebe `scope` e resolve a lista de documentos no servidor. `sources` vazio
quer dizer "todos os documentos daquela aba", não "todo o corpus"; a marcação do cliente
é interseccionada com a aba. Uma aba vazia responde `stats.mode = "empty_workspace"` com
uma mensagem própria, em vez de silenciosamente responder pelo corpus base — que é
exatamente a mistura que as abas existem para impedir. A divisão sai do carimbo TTL
(`metadata.expires_at` ausente = corpus base ingerido por CLI, presente = upload da
demo), então não houve banco, índice nem campo novo.

O `EngineStrip` existe por um motivo específico: **"busca híbrida" é fácil de afirmar e difícil de provar.** Com ele na tela, uma pergunta com número de norma mostra a lexical pesando, e uma pergunta conceitual mostra a vetorial pesando. O argumento se demonstra sozinho, sem eu narrar.

Ele é alimentado pelo `stats` que o backend devolve, e esse `stats` carrega o funil inteiro (`numCandidates` → vetorial/lexical → únicos após RRF → sobreviventes do rerank), mais os modelos e índices usados.

Se `/api/config` estiver indisponível, o app renderiza o shell offline com mensagem de recuperação. **Nunca regride pra tela de loading indefinido** — spinner infinito numa demo é pior que erro. Antes de cair nesse shell, `getConfig()` reenvia com backoff exponencial (4 tentativas): o uvicorn leva alguns segundos importando langchain/voyage e o launcher abre o browser assim que a porta responde, então sem o retry a primeira carga mostrava offline num backend que estava só subindo.

## Streaming

`POST /api/chat` devolve SSE com quatro tipos de evento:

```
meta   → fontes recuperadas e contribuição de cada motor (chega ANTES do primeiro token)
token  → delta de texto
done   → fim do turno
error  → mensagem de erro
```

`EventSource` não serve porque o endpoint é POST. Usa `fetch` + `getReader()`, acumulando buffer e quebrando em `\n\n`; chunk incompleto volta na próxima leitura.

**A ordem importa pra demo, e é deliberada:** o `meta` chega primeiro, então a `EngineStrip` e as `Sources` aparecem **antes** do texto começar a sair. O cliente vê a recuperação acontecer, depois vê a redação. Fica claro que o LLM escreveu sobre documento buscado, não de memória.

Não inverte essa ordem por conveniência de implementação.

## O roteiro que eu preciso conseguir executar no fim

1. **Pergunta com termo exato** — número de norma, sigla. Mostrar na `EngineStrip` que a lexical contribuiu.
2. **A mesma pergunta com outras palavras.** A vetorial contribui, e o RRF entrega os dois.
3. **Abrir as fontes.** Cada resposta cita os chunks que a fundamentaram, com o badge de motor e os scores vetorial → rerank. Nada de resposta sem procedência.
4. **Alternar pra `restrito`.** Conteúdo que estava fora da resposta aparece. Explicar que o filtro está nos dois estágios, não depois da fusão.
5. **Recarregar a página e retomar pelo `thread_id`.** A conversa está no Atlas.
6. **Ingerir um documento novo de outro formato** (XLSX ou PPTX) e perguntar sobre ele — pela CLI, ou arrastando na tela em **Base de conhecimento**. Depois marcar só ele e repetir uma pergunta do documento original: o assistente diz que aquilo não está no contexto. É a prova de que o filtro por `metadata.source` roda dentro das duas buscas, e é o momento em que o cliente entende que pode mandar o documento *dele* na reunião.
7. **Trocar o `.env` pra outro `CLIENT_ID`.** Outro database, outro documento, outra persona — **mesmo código rodando.**

O passo 6 é o que torna a PoV utilizável com qualquer cliente sem preparação prévia; o passo 7 é o fecho da conversa comercial. É ele que transforma "vocês fizeram uma demo pra um órgão" em "vocês têm uma plataforma".

## Nota sobre capturas de tela

O repositório é deliberadamente agnóstico de tenant, mas o app rodando pode
mostrar a organização real no topo, no nome do database, na resposta e nas
passagens citadas. **Substitui esses nomes por neutros no DOM imediatamente antes
de cada captura**, e mantém a nota embaixo das imagens dizendo que os nomes foram
trocados. Cortar depois não resolve.

## Antes de apresentar

- `setup_db.py` rodado e os dois índices `READY`.
- Uma pergunta de aquecimento, pra pagar o cold start do embedding e da geração fora da demo.
- Seletor de acesso em `publico`, pra que o passo 4 tenha contraste.


## Comportamento de resiliência integrado

Tratar EOF sem done como erro, conclusão única, CRLF e falhas de leitura; cancelar no unmount, impedir duplicação e limitar chat a 180 s. Upload 120 s e operações auxiliares 30 s. A implementação vigente está em `main`; consulte o estado atual de `../../REVIEW.md` para validação e propostas não aplicadas.
