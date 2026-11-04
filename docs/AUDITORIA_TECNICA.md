# COMPAC — Auditoria técnica, etapa zero

Data: 4 de novembro de 2026, fuso America/Sao_Paulo. Base auditada: `6a24fa763995cc52322b7c618ef9f8b95cbb369d`. Branch de trabalho: `audit/compac-corporativo`.

## 1. Diagnóstico executivo

O COMPAC tem uma base funcional de almoxarifado: autenticação, três perfis, cadastros, saldos por localização, movimentos com auditoria, empréstimos e devoluções parciais, requisições com atendimento atômico, chamados, manutenção, gastos, previsão e CSV. Os fluxos essenciais existentes passaram em SQLite e PostgreSQL locais. A interface e a PWA passaram nos testes de navegador existentes.

O sistema ainda precisa de correções antes de uma implantação piloto comercial. Foram reproduzidos três problemas prioritários: reenvio de movimentação duplica estoque; alteração da unidade cadastral muda a interpretação do histórico; limite de login pode ser reiniciado pela autenticação de outra conta. Também há falta de migrações versionadas e de uma rotina operacional de backup/restauração, leitura sem paginação, consultas N+1 e problemas de acessibilidade e atualização da interface.

Não foi confirmada vulnerabilidade crítica nesta revisão. Isso não equivale a um pentest completo ou à garantia de ausência de vulnerabilidades. A consulta de 24 versões de dependências ao OSV/PyPI não retornou advisories conhecidos naquele momento.

Esta entrega cumpre a instrução final do documento: diagnóstico, medições e plano antes da implementação. Nenhum arquivo da aplicação, saldo real, migração ou configuração de produção foi alterado. Nenhum deploy foi realizado. Os novos scripts geram dados fictícios em ambientes descartáveis.

## 2. Método e limites

- Revisão de todos os arquivos de aplicação e configuração versionados, inventário de rotas/modelos e leitura dos testes, sem presumir que o README prova uma funcionalidade.
- Execução da suíte existente, testes Chromium de interface/PWA e probes adicionais de segurança, integridade e acessibilidade.
- PostgreSQL 17.11 local, extraído em diretório temporário, com cluster exclusivo em loopback; nenhum uso do Neon de produção.
- Baseline com 100, 1.000 e 10.000 movimentos fictícios; percentis, tamanho de resposta, número de consultas e `EXPLAIN (ANALYZE, BUFFERS)` em PostgreSQL local.
- Ensaios de snapshot/restauração somente sobre dados fictícios. Eles demonstram procedimentos técnicos, não a existência de backups operacionais do produto.
- Não foram inspecionados tráfego, usuários, senhas, logs, backups, cotas ou configuração ao vivo da COMPAC/Render/Neon. Não houve teste em aparelho físico, Safari real ou rede móvel real. A arquitetura é de uma operação compartilhada; isolamento entre empresas não foi testado porque não existe no modelo.

As evidências brutas estão em [evidencias](evidencias/). Resultados positivos são amostrais. Problema confirmado, lacuna funcional e risco condicionado estão identificados separadamente.

## 3. Estrutura, arquitetura e duplicação

| Área | Arquivos | Responsabilidade e observação |
|---|---|---|
| Backend | `app/main.py`, 717 linhas | 37 rotas declaradas, validação, auth, SQL, estoque, relatórios e regras no mesmo módulo |
| Persistência | `app/db.py`, 176 linhas | 20 tabelas; adaptador SQLite/PostgreSQL; DDL gerado por substituições de texto; transações |
| Catálogos | `app/catalog.py` | Metadados compartilhados de validação/formulários, uma reutilização positiva |
| Inicialização | `app/serve.py` | Uvicorn, uma instância de worker, `0.0.0.0:$PORT`, proxy headers desativados |
| Interface | `app/static/app.js`, 1.951 linhas/92.572 bytes | SPA sem framework, roteamento por hash, formulários, cache, tabelas e ícones num IIFE |
| Estilos | `app/static/styles.css`, 3.112 linhas/53.368 bytes | Identidade visual e breakpoints existentes; sem justificativa para redesign |
| PWA | `manifest.webmanifest`, `sw.js`, `pwa.js`, offline e ícones | Cache restrito a ativos públicos offline; APIs e operações exigem rede |
| Testes | `tests/test_database.py`, `test_workflows.py`, `conftest.py`, dois scripts Chromium | Banco temporário por teste; PostgreSQL habilitado por variável de teste |
| Hospedagem | `render.yaml`, `.python-version`, requirements | Python/Render Free e PostgreSQL externo; variáveis privadas; deploy automático desligado no Blueprint |
| Ferramentas | `.agents/`, `.codex/`, `skills-lock.json` | Configuração de assistência/desenvolvimento, sem credencial real encontrada na configuração inspecionada |

Duplicação confirmada: a consulta de movimentos e seus JOINs reaparecem na listagem e no CSV (`main.py:460,692`); alertas são calculados tanto por `/alerts` quanto por `/dashboard`; validações de relações disparam consultas individuais; tabelas e cartões repetem montagem de HTML. Não se recomenda trocar toda a arquitetura. Extrair serviços de estoque/documentos, consultas reutilizáveis e módulos do frontend em mudanças incrementais, com testes antes/depois. A geração textual do DDL reduz duplicação, mas torna evoluções de schema frágeis; substituí-la gradualmente por revisões explícitas, sem reescrever históricos.

## 4. Rotas e autorização

Inventário completo: [rotas.json](evidencias/rotas.json), extraído da AST; também existe `/openapi.json` padrão do FastAPI e montagem de `/static`.

| Grupo | Rotas principais | Controle atual |
|---|---|---|
| Público | página inicial, manifesto, SW, offline, health, auth/status | Sem sessão; só ativos/status, sem dados operacionais |
| Credenciais | auth/setup, login, logout | Cabeçalho de proteção e validação condicional de Origin; setup bloqueia após primeiro usuário e exige token no Render |
| Sessão/leitura | auth/me, users, schema, catalog, stock, movements, loans | `current_user`, ativo e sessão não expirada |
| Operações | POST/PUT catalog; POST movements; POST requisitions/action; tickets/comentários; maintenance | `operator`, recusa CONSULTA |
| Administração | POST/PATCH users; GET audit | `administrator` |
| Regras internas | AJUSTE e APROVAR requisição | ADMIN também validado dentro da transação |
| Gestão | alerts, dashboard, forecast, export | `current_user`; leituras globais da operação |

13 leituras privadas sem sessão retornaram 401; tentativas CONSULTA de escrita, criação de administrador e acesso à auditoria retornaram 403. Alteração de senha, perfil ou ativação revoga sessões, já coberta pela suíte. Não foi demonstrada escalada de privilégio. Se houver necessidade de restrição por obra, unidade ou empresa, é preciso definir essa política: não há vínculo usuário→obra/empresa nem autorização por proprietário no modelo atual.

## 5. Banco e fluxos existentes

As 20 tabelas se organizam em: identidade (`users`, `sessions`); catálogo (`works`, `categories`, `locations`, `employees`, `materials`, `equipment`); estoque (`balances`, `movements`, `loans`); requisições (`requisitions`, `requisition_items`); atendimento (`tickets`, `ticket_comments`, `maintenance`); gestão (`expenses`, `consumption_profiles`, `production`); e trilha (`audit`).

`balances` usa chave material/local e `CHECK(quantity>=0)`; quantidades de estoque são inteiros em milésimos. SQLite usa `BEGIN IMMEDIATE`; PostgreSQL usa um advisory lock transacional global. Movimento, atualização de saldo, pendência e auditoria confirmam juntos ou fazem rollback. Essa proteção passou nos testes de concorrência e falha injetada; deve ser preservada até existir uma alternativa medida e testada.

| Fluxo | Confirmado no código e nos testes | Incompleto frente ao pedido corporativo |
|---|---|---|
| Material | Código único sem distinguir caixa; cadastro e edição auditados; campos de saldo estranhos são rejeitados | Estoque inicial/local/origem, ação separada Adicionar estoque e proteção da unidade histórica |
| Estoque | ENTRADA, SAIDA, TRANSFERENCIA, DEVOLUCAO e AJUSTE; saldo por local; ajuste só ADMIN com justificativa | Recebimento/NF multitem, idempotência, mínimo por local/obra, contagem física com aprovação |
| Empréstimos | SAIDA com funcionário; prazo; devolução parcial FIFO; recusa excesso; alerta vencido | Custódia transferível, avaria/perda, recibo e referência explícita devolução→empréstimo/patrimônio |
| Requisições | Cabeçalho e até 100 itens; aprovação; atendimento integral atômico; obra destino validada | Criação idempotente, reserva, atendimento parcial, paginação; lista tem N+1 |
| Patrimônio | Etiqueta única; condição/local/status; manutenção aberta única por unidade | Não há equipment_id em movimento/loan; manutenção não reserva o saldo quantitativo |
| Chamados | Estados, responsável elegível, comentários e histórico | Paginação, escopo de acesso se exigido, métricas/avisos operacionais |
| Gastos | Fornecedor em texto, documento/data/obra, quantidade, custo e total, CSV | Cadastro de fornecedor, documento multitem, conciliação com recebimentos; gasto não dá entrada no estoque |
| Produção/previsão | Coeficientes por obra/atividade, soma, produção e faltante vs saldo da obra | Sugestão de compras formal e consumo real vinculado à produção |
| Alertas | Mínimo global, empréstimo vencido, chamado urgente | Requisições urgentes, estoque mínimo local, EPI/CA/validade |
| Relatórios | CSV de estoque/movimentos/gastos/requisições/chamados/produção; auditoria últimos 2.000 | Excel/PDF nativos, comprovante consolidado, QR, indicadores de presença |
| Presença/EPI | Não encontrados modelos ou rotas específicos | Cadastro e histórico de presença, faltas/atrasos/justificativa; CA, tamanho, validade, entrega e comprovante EPI |

Detalhamento e plano operacional: [FLUXOS_OPERACIONAIS.md](FLUXOS_OPERACIONAIS.md) e [PLANO_MIGRACAO_ESTOQUE.md](PLANO_MIGRACAO_ESTOQUE.md).

## 6. Achados priorizados

| ID | Gravidade | Natureza | Evidência e consequência | Correção imediata recomendada |
|---|---|---|---|---|
| INT-01 | **Alta** | Bug reproduzido em SQLite/PG | Dois POSTs de entrada com mesmo Idempotency-Key retornam 201/IDs diferentes e saldo 4 em vez de 2 (`main.py:451`) | Idempotência persistente e transacional, com hash de payload e unicidade; reenvio concorrente testado |
| INT-02 | **Alta** | Bug reproduzido em SQLite/PG | PUT muda UN→KG e saldo/movimentos antigos passam a KG sem conversão (`main.py:369,460`) | Bloquear unidade com histórico; definir snapshots/conversão rastreável para evolução |
| SEC-01 | **Alta** | Falha reproduzida | Login correto de outra conta zera contador do host; 27 falhas contra alvo sem bloqueio (`main.py:238–253`) | Limites compartilhados por conta+origem, sem reset cruzado; configurar somente proxies confiáveis |
| REL-01 | **Alta** | Lacuna de operação | Só CREATE IF NOT EXISTS, sem versão/checksum/runner de migração (`db.py:167`) | Migrações aditivas versionadas e ensaiadas nos dois motores antes de novo schema |
| REL-02 | **Alta** | Lacuna de operação | Sem agendamento, retenção, responsável e validação de backup no produto/repositório | Definir RPO/RTO, automação, restauração isolada e simulado; ensaios desta auditoria são apenas locais |
| PERF-01 | Média | Gargalo medido | Listagem sem limites: 10 mil movimentos ≈3,8 MB, p95 317 ms no baseline SQLite | Paginação por cursor, filtros/ordenação no servidor e limites de exportação |
| PERF-02 | Média | Código e contagem medidos | 1.000 requisições geram 1.002 SQLs (`main.py:479–485`); varredura em itens | Buscar itens em lote; medir índices de FKs/consultas reais |
| UX-01 | Média | Bug reproduzido | Atualizar mantém nome de categoria antigo vindo do cache (`app.js:325–334,1070,1879`) | Invalidar relações de forma consistente e proteger respostas atrasadas |
| UX-02 | Média | Acessibilidade reproduzida | Dialog sem nome acessível; Tab sai para trás do menu mobile; textos pequenos com contraste <4,5:1 | Nomear diálogo, gerir foco/inert, corrigir contrastes e testar teclado/leitor |
| UX-03 | Média | Layout e custo medidos | Atalhos cortados no dashboard 1440 px; 10 mil linhas levam ≈3,5 s para renderizar e ≈476 ms por filtro | Ajuste responsivo pontual; renderização limitada/paginada, debounce e medição |
| UX-04 | Média | Bug de data reproduzido | Default UTC em despesas sugere 05/11 quando em São Paulo ainda é 04/11 às 22h30 (`app.js:1312`) | Usar data do fuso operacional e testar fronteiras de dia |
| OP-03 | Média | Lacuna de modelo | Patrimônio/manutenção sem conciliação com saldos e empréstimos individuais | Definir vínculo de unidade, custódia e disponibilidade antes de prometer rastreabilidade individual |
| OP-04 | Média | Lacuna funcional | Estoque não agrega pendências nem total sob controle | Agregar balances e loans separadamente para evitar multiplicação por JOIN |
| SEC-02/03 | Média | Lacunas confirmadas | Recuperação de senha sem fluxo; falhas de login sem auditoria | Fluxo seguro definido com negócio; eventos minimizados, limites e retenção |
| SEC-04 | Média | Defesa a reforçar | Origin opcional/Referer ignorado; probe não prova CSRF de navegador | Documentar política, ampliar testes e endurecer antes de flexibilizar CORS |
| OBS-01 | Média | Lacuna confirmada | Sem métricas de latência/erros/locks e sem tratamento próprio para timeouts operacionais | Instrumentar tempos/erros com dados minimizados e alertas de operação |
| DEP-01 | Baixa | Configuração | Lock sem hashes; dependências de teste em produção | Separar grupos e gerar lock verificável na fase de pipeline |
| SEC-05 | Baixa | Exposição deliberável | `/openapi.json` público apesar de docs/redoc desligados | Decidir política do contrato público; não há dado operacional exposto no contrato |
| OP-07 | Baixa | Regra a definir | Duplicidade é por código; não há equivalência semântica de descrição | Normalização e alerta de candidato; não mesclar materiais automaticamente |

Não foram encontrados dados reais corrompidos: não foram lidos dados reais. Riscos condicionados, não bugs provados: identidade da origem atrás da proxy Render; desempenho Neon/latência de rede; memória sob carga concorrente; equivalência Unicode NOCASE/LOWER; precisão de dinheiro na conversão NUMERIC/Decimal→float/REAL; política de acesso horizontal por obra; CVEs da imagem e bibliotecas nativas. Esses pontos precisam de validação específica.

## 7. Segurança e dependências

Controles positivos: scrypt com salt aleatório e comparação constante; token de sessão de 32 bytes, somente hash no banco; cookie HttpOnly/SameSite Strict/Secure configurável; sessão de oito horas e revogação; permissões no backend; SQL parametrizado e identificadores derivados de listas fechadas; escaping de HTML e CSP; neutralização de fórmulas em CSV; TLS PostgreSQL com verify-full; sem fallback silencioso para SQLite quando PostgreSQL falha.

Avaliar Argon2id e formato versionado de hash com migração gradual e benchmark. O scrypt atual é um mecanismo válido, mas a seleção de custo precisa ser comparada às recomendações OWASP vigentes e à memória disponível. Não invalidar senhas existentes por troca de algoritmo.

CSRF: cabeçalho customizado, JSON, ausência de CORS permissivo e SameSite Strict já fornecem defesa. O fato de TestClient aceitar Referer externo sem Origin não comprova exploração a partir de navegador externo. Não foi declarada vulnerabilidade crítica de CSRF.

Retenção/minimização de pessoas, auditoria e logs não têm política implementada. Definir responsáveis, prazos e resposta a incidentes. A auditoria não é imutável contra administrador do banco; controle operacional e backups são necessários.

Relatórios: [SEGURANCA.md](SEGURANCA.md) e [DEPENDENCIAS.md](DEPENDENCIAS.md), com fontes e respostas de consulta. `pip check`: sem requisitos quebrados. Existe aviso de depreciação Starlette TestClient/httpx, sem falha dos testes.

## 8. Desempenho: linha de base e limites

O [relatório de performance](PERFORMANCE.md) contém método, p50/p95/p99, bytes, SQLs, planos e diferenças entre os cenários. Sem otimizações nesta fase, a coluna “depois” permanece pendente.

As medições locais sequenciais não validam SLA de produção. Separar no piloto: tempo servidor aquecido, tempo de SQL, rede/browser e cold start da hospedagem. O lock global atual favorece integridade e limita vazão; não substituí-lo por paralelismo sem medir contenção e preservar ordenação de bloqueios/atomicidade.

## 9. Testes e evidências

| Verificação | Resultado | Escopo |
|---|---|---|
| `.venv/bin/python -m pytest -q` | **26 passed**, 1 aviso, 2,65 s | SQLite descartável |
| Mesma suíte com COMPAC_TEST_DATABASE_URL local | **50 passed**, 1 aviso, 7,15 s | SQLite + PostgreSQL 17.11; schemas isolados |
| `node tests/browser_smoke.cjs` | **PASS** | Cadastro, material, estoque, chamados/comentários, navegação desktop/mobile; fictício |
| `node tests/pwa_smoke.cjs` | **PASS** | Manifesto, ícones, SW, cache público exato, offline, formulário e atualização; Chromium |
| Probes operacionais | **Reproduzidos nos dois bancos** | Duplicidade, unidade histórica, validação, empréstimo parcial e rollback injetado |
| Probes segurança | **Controles e falha documentados** | 401/403, sessão, throttle, origem, contrato público; SQLite |
| Baseline de APIs | **Concluído** | 100/1k/10k fictícios, percentis/SQL/bytes; sem rede externa |
| EXPLAIN ANALYZE | **15 planos coletados** | PostgreSQL local, 5 consultas × 3 volumes |
| Snapshot/restauração SQLite | **Tabelas iguais** | Dados gerados, integralidade e comparação de linhas |
| pg_dump/pg_restore | **PASS** | 60 tabelas, 54 sequences identity, 210 constraints e 111 índices nos 3 schemas sintéticos |
| Migração versionada | **Não existe para testar** | Plano proposto; nenhuma migração aplicada |

Os probes de bugs são evidências de auditoria: observam a implementação atual, incluindo comportamentos incorretos; uma execução bem-sucedida do probe não significa que o bug foi corrigido. Na fase B, converter os cenários relevantes em regressões que exijam o comportamento corrigido.

## 10. Ordem recomendada e impactos

### Fase A — esta entrega

Auditoria, inventário, baseline, evidências e plano de migração. Arquivos novos em `docs/` e `scripts/`; nenhum comportamento da aplicação modificado. Risco operacional da entrega: sem execução automática dos scripts e sem deploy.

### Fase B — segurança e integridade

1. Bloquear alteração de unidade com histórico e definir conversões futuras.
2. Persistir idempotência de movimentos, incluindo reenvio concorrente e conteúdo diferente.
3. Corrigir throttle por conta/origem, observabilidade de falhas e política de recuperação/origem.
4. Corrigir atualização de relações, datas e foco/contrastes pontualmente, mantendo a identidade visual.

Impactos: clientes antigos precisam adotar chave de operação para garantia de reenvio; alterações cadastrais antes permitidas passam a ser rejeitadas com orientação; limites de login precisam evitar bloquear usuários legítimos. Tudo primeiro em ambiente descartável.

### Fase C — migração, consultas e performance

Runner de migrações com versão/checksum, backup/restauração, paginação/filtros, remoção de N+1, índices medidos, métricas de latência/erro e reconciliação. Atualizar frontend junto com contrato paginado. Definir RPO/RTO e provar restauração antes da aplicação autorizada de qualquer alteração em produção.

### Fase D — documentos e funcionalidades operacionais

Priorizar estoque inicial e recebimento/NF multitem pelo pedido anterior, usando o [plano aditivo](PLANO_MIGRACAO_ESTOQUE.md); depois entregas em lote/comprovante. Presença e EPI recebem modelos próprios e critérios validados, sem cálculo de folha/desconto. Não acoplar essas três funcionalidades numa migração única.

### Fase E — inventário, alertas e relatórios

Contagens/divergências com aprovação e contramovimentos; mínimo local/obra, compras, urgências, fornecedores, reconciliação patrimonial e exportações novas. Definir custos/baixas e responsabilidade pela contagem.

### Fase F — interface e preparação comercial

Modularizar incrementalmente, rever telas/teclado/dispositivos, manuais de administrador/operador, monitoramento, changelog, demonstração fictícia e personalização por cliente. Avaliar multiempresa sem compartilhar dados prematuramente. Licenciamento, cobrança e dependências comerciais exigem decisão separada.

Mudanças de alto risco — migração de dados, alteração de semântica de empréstimos/patrimônio, recuperação de administrador, mudança de locks e produção — precisam de plano concreto, ensaio de reversão e autorização antes da execução. O pedido desta fase não autoriza deploy ou alteração de banco real.

## 11. Critérios para um piloto

- Corrigir e testar os três achados altos reproduzidos; repetir consulta de vulnerabilidades e mitigar achados críticos conhecidos.
- Passar nos fluxos de estoque, concorrência, permissões, devoluções, falha entre itens e idempotência em ambos os motores.
- Migração reproduzível de fixture da versão atual, com contagens/somas/IDs preservados e restauração isolada verificada.
- Backup automático com retenção, responsável, verificação e RPO/RTO acordados.
- Medir metas de APIs e interface em homologação representativa, com rede/cold start separados.
- Fechar dispositivos de suporte, acessibilidade, recuperação de acesso, monitoramento e manuais.
- Autorizar explicitamente o piloto. Os testes desta auditoria, sozinhos, não atendem todos esses critérios.
