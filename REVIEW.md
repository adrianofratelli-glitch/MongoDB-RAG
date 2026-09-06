> Estado vigente: melhoria `fadc914` aprovada pelo usuário e integrada em `main`. As menções abaixo a aprovação pendente são históricas. As propostas de core/schema/dataset continuam sem aplicação.

# Revisão de engenharia e design — tjgo-rag-multitenant

## Resultado

Pool único sob concorrência; browserslist/nanoid corrigidos; reconexão recarrega config do tenant e status tem timeout de 5 s.

Branch `review/codex-improvements`, criada de `main` em `540393977a5e9d102d742c8516e9aa8b632d6829`. Sem merge, push, troca de biblioteca core, alteração de schema ou dataset.

## Commits de correção

- `5a6790c fix: serialize MongoDB client initialization`
- `4e90fe9 fix: update vulnerable browserslist and nanoid dependencies`
- `342c355 visible-change: restore tenant configuration when reconnecting`

## Commits visible-change

- `342c355 visible-change: restore tenant configuration when reconnecting`

## Validação

- 43 testes unitários passaram. Browser confirmou config recuperada e banner de erro removido usando respostas sintéticas locais.
- Build de produção passou; análise Ruff E9/F63/F7/F82 com target Python 3.12 passou.
- Browser com APIs bloqueadas: 1440×1000, 768×1024 e 360×800; sem pageerror e sem overflow horizontal no shell inicial; link de salto transfere foco ao conteúdo.
- As 14 cópias de pov-signature.css permanecem idênticas; lang pt-BR confirmado. Nenhuma alteração na camada compartilhada de CSS.
- Auditor de portas passou: registro e configurações alinhados.
- npm audit do lockfile após correções: 0 altos, 0 críticos, 0 moderados e 0 baixos.

## Sugestões não aplicadas e limites

- `db.py:verify_tenant_identity` usa find seguido de insert; dois primeiros boots simultâneos podem causar DuplicateKeyError. Corrigir com operação atômica mantendo a verificação de identidade exige revisão do contrato de bootstrap persistido; não aplicado.
- Advisories de pypdf/aiohttp no ambiente são relevantes ao upload. Os requirements não descrevem integralmente todos os pacotes instalados; consolidar dependências de ingestão em rodada própria.
- ACL escolhida na UI é limite documentado da demo, não autenticação real; nenhuma mudança de schema/tenant aplicada.

A verificação visual cobre o shell offline e abas acessíveis sem backend, não todos os estados de dados. Não certifica contraste de cada componente, comportamento touch completo ou toda a navegação com Atlas. Fluxos reais de escrita/carga não foram executados para preservar datasets. Nenhuma comparação de performance foi inventada. Evidências locais: `/tmp/codex-portfolio-review/`.

## Dependências Python

Auditoria do ambiente instalado, não de uma resolução limpa do manifesto; ferramentas de desenvolvimento podem aparecer junto com runtime. Os IDs abaixo não equivalem a exploração confirmada na PoV. Reconciliar versões instaladas/manifests e testar compatibilidade; atualizações core/major ficaram fora desta rodada. Pacotes de ferramenta e componentes extras do venv também não foram alterados fora da branch.

| Pacote instalado | Versão | Advisory | Versões corrigidas informadas |
|---|---|---|---|
| aiohttp | 3.14.1 | PYSEC-2026-3545, PYSEC-2026-3546, PYSEC-2026-3547 | 3.14.2, 3.14.3 |
| pip | 26.1 | PYSEC-2026-196, PYSEC-2026-3721 | 26.1.2, 26.2 |
| pypdf | 6.14.2 | PYSEC-2026-3655, PYSEC-2026-3656, GHSA-jp53-mhqp-8xcg, GHSA-23w6-3w8w-8484, GHSA-763m-79hh-57f2, GHSA-fc8x-2rww-xw9m | 6.15.0, 6.16.0, 6.16.1 |

## Segredos e compartilhamento

Varredura por padrões de chaves privadas, chaves Anthropic/AWS e URI MongoDB autenticada no histórico Git local alcançável: nenhuma credencial real confirmada; matches encontrados eram placeholders conhecidos. Limite: não é scanner de entropia, não cobre objetos inacessíveis, texto em screenshots nem logs externos.

Nenhum import/referência estática a `_shared/grove_client.py` foi encontrado nesta PoV. Configuração própria de gateway/ambiente não constitui dependência de código desse módulo. `_shared` permaneceu intocado; consumidores externos/dinâmicos não são garantidos por busca estática. Relatório separado: `../REVIEW_SHARED.md`.

## Segunda rodada — melhorias adicionais

Inicialização concorrente de tenant_identity agora captura DuplicateKeyError e verifica a identidade vencedora; tenant diferente continua falhando fechado. Mesmo documento e índice _id existentes. 45 testes passaram, incluindo disputa com identidade igual/diferente. Merge continua bloqueado pelo visible-change pendente.


## Fechamento final — 2026-09-05

Esta seção atualiza o estado dos achados históricos acima.

- Aplicado/reavaliado: Commit 342c355 validado e integrado via fast-forward até 30b3139; pisos aiohttp ≥3.14.3,<4 e pypdf ≥6.16.1,<7 adicionados nesta rodada.
- Validação: 45 testes; build; backend desconectado/reconectado por interceptação HTTP, erro visível e botão utilizável, erro limpo na recuperação, navegação funcional; npm/pip-audit sem achados.
- Propostas e limites restantes: Race de identidade do tenant já corrigida na revisão integrada. ACL da UI não é autenticação: propor identidade verificada no backend antes de exposição multiusuário; melhora isolamento, mas altera fluxo/contrato e exige aprovação. Sem mudança de corpus/schema/tenant.
- pip-audit atual: Nenhum advisory de Python encontrado no ambiente auditado.
- Ambiente: pip 26.2.1 nos ambientes que possuem pip; FinScope mantém uv sem pip. Essa atualização local não altera arquivos de dependências das PoVs.
- `_shared`: nenhum importador estático comprovado nesta PoV; apenas smoke consome o helper no inventário.

Compatibilidade adicional: `pip check` detectou `langgraph-checkpoint-mongodb 0.4.0` exigindo `pymongo<4.17`, enquanto o ambiente já possui `pymongo 4.17.0`. Os patches desta rodada não alteraram esses pacotes. Proposta: resolver versões de driver/checkpointer conjuntamente e testar checkpoint real; evita combinação fora do contrato, mas envolve core/downgrade e requer aprovação. Os 45 testes locais não eliminam essa pendência.

Validação complementar (2026-09-06), após religamento do cluster: ping e identidade existente OK. Backend temporário real retornou HTTP 200 com Atlas online. Bloqueio HTTP apenas no navegador mostrou erro; ao liberar a conexão, botão recuperou a tela, abas continuaram responsivas e houve zero pageerror. Sem fixtures de status nesta confirmação; nenhum upload/chat/escrita de dataset, restart do daemon ou stress do portal.


## Homologação de resiliência e UI

- Melhoria: Tratar EOF sem done como erro, conclusão única, CRLF e falhas de leitura; cancelar no unmount, impedir duplicação e limitar chat a 180 s. Upload 120 s e operações auxiliares 30 s.
- Isolamento: `review/codex-homologation`, baseada no HEAD `02da300`. Mudança de estado observável; aguardando aprovação individual, sem merge.
- Validação: build passou; UI offline em 1440×1000, 768×1024 e 360×800 sem pageerror nem overflow horizontal; skip link transfere foco. 5 testes novos de transporte/polling neste repositório. As suítes locais anteriores foram reexecutadas; resultados consolidados no vault PoVs-Handoffs.
- Limite: teste offline/fixture não certifica cenário real completo nem ausência de bugs. Não houve alteração de schema, dataset ou dependência core.
- Propostas preservadas: Race de identidade do tenant já corrigida na revisão integrada. ACL da UI não é autenticação: propor identidade verificada no backend antes de exposição multiusuário; melhora isolamento, mas altera fluxo/contrato e exige aprovação. Sem mudança de corpus/schema/tenant.
- `_shared` e daemon do portal não foram alterados nesta rodada.
