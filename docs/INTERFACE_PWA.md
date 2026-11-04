# Auditoria da interface, PWA e experiência operacional — COMPAC

Data: 04/11/2026. Código-base auditado: `6a24fa7`. Trabalho somente de diagnóstico, sem alterar arquivos da aplicação, sem acessar serviços de produção e com bancos SQLite temporários e dados fictícios. Chromium local com Playwright; viewports 1440×1000 e 390×844. Não equivale a uma certificação WCAG ou teste nativo de aparelhos.

## Verificações executadas

Comandos na raiz do repositório, com rede de localhost permitida pelo sandbox:

```sh
COMPAC_TEST_ARTIFACTS=/tmp/compac-audit-ui COMPAC_TEST_PORT=8822 node tests/browser_smoke.cjs
env -u PWA_BASE_URL PWA_TEST_PORT=8823 node tests/pwa_smoke.cjs
node scripts/audit_frontend.cjs
node scripts/audit_dates.cjs
```

Ambos os testes existentes terminaram com exit code 0. Saídas exatas:

```text
PASS: cadastro inicial, material pelo formulário, entrada de estoque, chamado/comentário/status, telas e navegação mobile sem erros JavaScript.

PWA OK: Chromium installability, manifest/icons, SW scope, exact public cache, offline GET/POST rejection, form preservation, fallback/retry, Android/iOS help copy.
SW update OK: pending update preserves the form; reload occurs only after explicit confirmation.
Native Safari/iPhone installation was not tested. No resources were published.
```

Os testes de navegador existentes cobrem cadastro inicial, criação de material no formulário, entrada de estoque, criação/edição/comentário de chamado, navegação pelas telas e menu mobile. Não cobrem todos os formulários, todos os perfis ou a totalidade de teclado/contraste.

## Achados confirmados

### UI-01 — Médio — Atualizar dados preserva relações obsoletas

- Evidência: `app/static/app.js:325` reutiliza `S.cache` para relações; `:1070` recarrega a entidade principal com `force=true`, mas `loadRelations` não força a atualização; botão Atualizar chama somente `route()` (`:1879`, próximo ao handler).
- Reprodução: abrir Materiais com categoria “Categoria anterior”; alterar a categoria por uma segunda requisição legítima (HTTP 200); clicar em Atualizar dados. A API de categorias retorna “Categoria atualizada”, mas a tabela de materiais continua exibindo “Categoria anterior”.
- Resultado no JSON: `oldVisible=true`, `newVisible=false`, `serverCategory='Categoria atualizada'`.
- Impacto: descrições de categorias/localizações/obras/funcionários vistas em referências podem continuar antigas em uma sessão mesmo após o comando explícito de atualização. A aplicação não é atualizada em tempo real por push.
- Correção recomendada: invalidar relações no refresh explícito, ou cache com revisão/TTL, mantendo deduplicação de requisições em andamento.

### UI-02 — Médio — Atalhos do dashboard cortados em desktop 1440 px

- Evidência: `app/static/styles.css:1196` usa quatro colunas `repeat(4, 1fr)`; conteúdo mínimo dos cards excede a largura da coluna lateral do dashboard; painel corta o excesso.
- Medição: painel entre x=958,80 e x=1406; grid com 405 px de largura e `scrollWidth=606`. “Abrir chamado” se estende até x=1420,67 e “Empréstimos” começa em x=1432,67 e termina em x=1586,03, fora do painel. Screenshot em `docs/evidencias/interface/dashboard1440.png` e screenshot do teste funcional `docs/evidencias/interface/painel-desktop.png`.
- Impacto: atalhos parcialmente ou totalmente invisíveis, embora outros caminhos do menu continuem disponíveis. O teste que mede somente transbordamento horizontal do documento não detecta clipping interno.
- Correção recomendada: grid que responda à largura do próprio painel, com duas colunas quando necessário e `minmax(0,1fr)`, sem redesign.

### UI-03 — Médio — Contraste insuficiente em textos do primeiro acesso

- Evidência: `app/static/styles.css:13`, `:349`, `:466`, `:479`; medições de estilos computados, fundo branco real do painel.
- `#auth-description`: texto 13 px, RGB(119,130,123), razão 3,99:1.
- `#auth-help`: texto 10 px, RGB(139,151,142), razão 3,04:1.
- `.auth-security`: texto 10 px, RGB(134,148,136), razão 3,18:1.
- Estes três exemplos de texto pequeno ficam abaixo do objetivo 4,5:1 de WCAG 2.2 AA, critério 1.4.3. Outros componentes não foram todos medidos; não generalizar a medição a toda a interface.
- Correção recomendada: escurecer tokens de texto secundário e rever todos os estados, preservando a paleta.

### UI-04 — Médio — Menu mobile deixa o foco no conteúdo encoberto

- Evidência: `app/static/app.js` nas funções `openSidebar`/`closeSidebar` (próximas a :524) altera classe e `aria-expanded`, mas não transfere o foco ao menu, nem torna o restante inerte, nem restaura foco de forma controlada.
- Reprodução com largura 390 px: clicar `#menu-toggle`; foco permanece `menu-toggle`; pressionar Tab desloca o foco para `#global-search`, fora de `#sidebar`, por trás da sobreposição.
- Evidência em `sidebarFocus` no JSON e `docs/evidencias/interface/sidebar-focus.png`.
- Impacto: usuário de teclado pode interagir com controles encobertos e não alcança a navegação pelo caminho esperado. Conferir critérios WCAG 2.4.3 e 2.4.11 com auditoria completa; esta verificação isolada não certifica conformidade.
- Correção recomendada: tratar drawer como diálogo modal no breakpoint mobile, transferir foco, manter foco no drawer e devolvê-lo ao acionador ao fechar.

### UI-05 — Médio — Data padrão usa UTC e pode cair no dia seguinte no Brasil

- Evidência: `app/static/app.js:1312` preenche novos campos de data por `new Date().toISOString().slice(0,10)`.
- Reprodução determinística com relógio em `2026-11-05T01:30:00Z` e timezone `America/Sao_Paulo`: dia local `2026-11-04`, campo `purchase_date` do formulário de Despesas preenchido `2026-11-05`.
- Impacto: compras/produção podem ser registradas no dia seguinte se o usuário aceitar o valor padrão depois das 21h de São Paulo. Não se confirmou alteração em registros existentes; problema é o preenchimento inicial da interface.
- Correção recomendada: construir o valor YYYY-MM-DD no fuso operacional escolhido, com testes nas fronteiras de dia.

### UI-06 — Baixo — Diálogos genéricos não possuem nome acessível

- Evidência: `app/static/index.html:257` declara `<dialog id="form-dialog">` sem `aria-labelledby`/`aria-label`; `app/static/app.js:475` cria título `<h2>` sem ID vinculado.
- Reprodução: abrir Novo material e consultar a árvore de acessibilidade via CDP. Resultado: `role='dialog'`, `name=''`.
- Impacto: leitores de tela não recebem o nome da janela ao entrar. O diálogo nativo já fornece modalidade e gerenciamento básico de foco, portanto a estrutura pode ser mantida.
- Correção recomendada: título com ID e referência estável `aria-labelledby` no diálogo. O diálogo específico da PWA já tem esse vínculo.

### UI-07 — Médio — Renderização e busca síncrona não escalam a tabelas grandes

- Evidência: `app/static/app.js:406` cria todas as linhas com template e `innerHTML`; `:417` percorre todas as linhas e atualiza `hidden` em cada evento `input`; `:1066`/`:1117` materializa todos os registros do catálogo. Não há paginação/virtualização frontend. `options` (`:363`) também monta todo catálogo em cada select.
- Medição sintética abaixo comprova aumento de tempo perceptível no navegador local. É diagnóstico do custo DOM, não p95 de produção nem benchmark de API.
- Correção recomendada: paginação e pesquisa no servidor com limite máximo, componentes de tabela reutilizáveis e seleção pesquisável para catálogos. Debounce pode reduzir trabalho por digitação, mas não resolve descarga/renderização de toda a base.

## Linha de base de tabelas no navegador

Probe `scripts/audit_frontend.cjs`: intercepta somente GET do catálogo de materiais no navegador e fornece 100/1.000/10.000 registros fictícios para o renderer real. Aplicação/backend seguem em SQLite descartável; dados grandes não são gravados. Tempo de renderização medido de clique Atualizar até número esperado de linhas e duas animation frames, incluindo automação local; filtro mede handler síncrono e layout forçado. Uma amostra por volume, máquina compartilhada, sem limitação de CPU; não usar para prometer latência em aparelhos reais.

| Linhas | Renderização observada | Busca/filtro síncrono observado |
|---:|---:|---:|
| 100 | 103 ms | 6,4 ms |
| 1.000 | 432 ms | 47,5 ms |
| 10.000 | 3.489 ms | 475,7 ms |

A UI pode bloquear quase meio segundo por input com 10.000 linhas nesta amostra. O probe usa materiais; o padrão de tabelas também é usado em movimentações, porém não extrapolar estes tempos exatos a outro conjunto.

## Funcionalidades existentes e controles observados

- Identidade visual coerente em desktop e mobile; revisão visual das capturas do teste funcional e ausência de transbordamento horizontal da página no fluxo mobile testado. Existem problemas internos de clipping conforme UI-02.
- Navegação por hash com estados de carregamento/erro e guarda de versão (`app.js:634`, `:691`) contra resposta antiga sobrescrever a tela atual.
- Helper de API exibe mensagem de falha de rede; não há timeout/AbortController em `app.js:274`–`:312`. É risco de espera prolongada, sem incidente de rede real atribuído ao produto nesta auditoria.
- Dados interpolados pelo frontend passam, em geral, por `E()`/`textContent`. Não foi confirmado XSS pelos fluxos cobertos. Revisão de segurança do backend é outra frente.
- Formulários modais desabilitam o botão durante envio, tornam o corpo inerte e restauram estado (`app.js:479`–`:503`); autenticação também desabilita botão. Isso ajuda contra cliques repetidos normais, mas não garante idempotência de operações após retry/reenvio HTTP. O POST de movimento envia somente o corpo, sem chave de idempotência (`app.js:1403`).
- Formulário de material NÃO contém estoque inicial/localização/origem: nomes atuais em `initialStockFields` no JSON. O botão genérico Movimentar cria uma ENTRADA separada. A edição cadastral preserva o modelo de metadados, sem quantidade de saldo editável. Estoque inicial/Adicionar estoque/nota multi-itens são requisitos novos.
- Despesas informa explicitamente que o cadastro não movimenta estoque (`app.js:1356`); fornecedor/documento/custo de despesas não constituem recebimento rastreável.
- Tela Estoque mostra saldo disponível por localização e soma disponível global (`app.js:778`–`:832`), mas não expõe lado a lado emprestado e total sob controle; há uma aba separada de empréstimos em aberto.
- `app.js`: 1.951 linhas, 92.572 bytes; `styles.css`: 3.112 linhas, 53.368 bytes. Responsabilidades API, estado, navegação, formatação, tabelas, todos os módulos operacionais e diálogos estão na mesma IIFE. Isso é risco de manutenção; tamanho isolado não comprova gargalo de download. Parte de formulário/tabela já é compartilhada; evitar reescrita total.
- Busca atual combina os campos global/local na página, com filtros de status. É filtragem de dados já carregados, não pesquisa em toda base no servidor.

## PWA e service worker

Conforme `app/static/sw.js:5`–`:9`, somente offline.html, CSS/JS públicos de indisponibilidade e ícones são cacheados. APIs e métodos diferentes de GET são ignorados (`:27`), documentos usam rede com fallback (`:32`–`:37`). Teste validou conteúdo exato do cache e rejeição de GET e POST de API em offline: não houve cache de dados de usuários nem fila de writes.

Atualização de SW espera aceite explícito antes de recarregar (`pwa.js:126`–`:139`); teste alterou cópia descartável de sw.js e preservou formulário antes de confirmação. Manifesto possui ícones corretos, escopo raiz, display standalone; installability Chromium sem erros. Não houve instalação nativa em Android/iOS; emulação de UA testa texto de ajuda, não plataforma. Registrar isso como lacuna, não aprovação nativa.

Foco e mensagens usam recursos existentes: skip-link, rótulos nos campos, aria-label para botões de ícone, toast com role status/alert, outline focus-visible e prefers-reduced-motion. Conformidade WCAG 2.2 AA exige avaliação adicional de todos os componentes, contraste, zoom, toque e leitores de tela.

## Evidências preservadas e prioridades

- `scripts/audit_frontend.cjs`: probe funcional/AX/contraste/menu/cache/layout.
- `scripts/audit_frontend.cjs`: mesmo probe mais baseline de tabelas; `docs/evidencias/interface/probe-results.json` contém tempos e resultados.
- `scripts/audit_dates.cjs` e `date-probe-results.json`: timezone/data padrão.
- `docs/evidencias/interface/dashboard1440.png` e `sidebar-focus.png`: capturas do probe.
- `docs/evidencias/interface/painel-desktop.png`, `painel-celular.png`, `chamado-celular.png`: teste funcional existente.

Recomendação: corrigir integridade/idempotência no backend em prioridade maior que mudanças visuais. Depois corrigir refresh e data (sem migração), resolver contraste/nome/foco/clipping com ajustes pequenos, e só então modularizar incrementalmente e introduzir paginação junto ao contrato das APIs. Não alterar mecanismo de cache para guardar dados de estoque offline sem projeto específico.
