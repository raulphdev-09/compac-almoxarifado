# Fase B — segurança e integridade

Branch: `fix/compac-seguranca-integridade`. Base: auditoria `bcdff6f`. Implementação e validação em dados descartáveis; **sem aplicação no banco real e sem deploy**.

## Correções entregues

| Achado da auditoria | Comportamento desta versão | Evidência |
|---|---|---|
| INT-01, reenvio duplica estoque | POST de movimento exige Idempotency-Key; mesma chave/usuário/conteúdo retorna ID original; conteúdo diferente retorna 409 | 36 casos de integridade por motor e navegador com resposta perdida após commit |
| INT-02, unidade reinterpreta histórico | Unidade e controle patrimonial não mudam após vínculos de saldo, movimento, empréstimo, patrimônio, requisição, gasto ou perfil de consumo | Testes de cada vínculo, inclusive saldo zero/empréstimo encerrado; descrição/status continuam editáveis |
| SEC-01, limite reiniciado por outra conta | Falhas persistidas no banco; janela 300 s, 10 falhas por conta e 30 por origem observada; sucesso não apaga contadores | Entre clientes, contas, origens, expiração, headers forjados e 12 falhas concorrentes |
| SEC-03, falhas sem trilha | LOGIN_FALHOU, TROCA_SENHA_FALHOU e evento no limiar de bloqueio confirmados sem senha/token/nome em detalhes | Testes verificam conteúdo e volume dos eventos; a rejeição não desfaz a gravação |
| SEC-04, política de origem parcial | Origin exato, Referer como fallback e Fetch Metadata same-origin nas escritas; configuração malformada/cross-site recusados | Matriz de requisições legítimas, externas, null, inválidas e header-only explícito |
| SEC-02, troca própria ausente | POST auth/password exige senha atual e nova diferente, registra evento e revoga todas as sessões | Senha errada, usuário sem sessão, CONSULTA própria, múltiplas sessões e rollback da auditoria |
| UX-01..04 e UI-06 | Relações atualizadas no refresh; data local; atalhos sem clipping; contraste, foco do menu e nome do diálogo corrigidos | Novo teste de navegador e smokes existentes |

Não houve mudança para Argon2id: scrypt e hashes existentes foram preservados. Evolução do algoritmo exige benchmark de custo/memória e formato versionado; não é necessária para corrigir o bypass de throttle reproduzido. Nenhum canal público de recuperação ou serviço externo foi criado. Política operacional de acesso: [RECUPERACAO_ACESSO.md](RECUPERACAO_ACESSO.md).

## Atomicidade, estrutura e histórico

Migração aditiva `001_security_integrity`, com checksum, adiciona `idempotency_requests`, `auth_attempts`, índices de limite e `schema_migrations`. Não altera ou recalcula os saldos, movimentos, usuários ou empréstimos antigos. A tabela de idempotência guarda resposta e hash de conteúdo sob chave primária usuário/escopo/chave.

Mantidos BEGIN IMMEDIATE em SQLite e advisory lock transacional global em PostgreSQL. Movimento, projeção do saldo, empréstimo, auditoria e resposta idempotente ficam na mesma transação. Falha na auditoria ou na gravação da chave reverte tudo. A leitura da chave e seus efeitos são serializados; não se usa um cache em memória para essa garantia.

DDL é executado instrução por instrução sob transação; não há executescript com commit implícito. O runner recusa checksum divergente, tabela/coluna/chave primária ausente e índices esperados ausentes. A checagem estrutural é limitada aos componentes declarados desta revisão; não é detector universal de alterações manuais do banco.

## Mudança de contrato HTTP

Todo POST `/api/movements` precisa de `Idempotency-Key` ASCII entre 1 e 128 caracteres, começando com letra ou número e contendo letras, números, ponto, hífen, sublinhado ou dois-pontos. Ausência/inválido: 422. Reuso com outro conteúdo: 409. Replay válido retorna 201 com a resposta original, sem novos efeitos. O hash usa JSON com chaves ordenadas; o cliente deve reenviar o mesmo conteúdo, inclusive os tipos dos números.

O frontend gera uma chave por intenção no modal, mantém a chave ao tentar novamente após erro de rede e troca a chave quando o usuário muda os dados para uma nova intenção. Há guarda pending contra submissões concorrentes da mesma janela. Fechar/reabrir inicia outra intenção; conferir o histórico antes de repetir uma operação cujo resultado ficou incerto em outro dispositivo. Não há deduplicação por semelhança de quantidade/data: duas entregas iguais podem ser legítimas.

Clientes externos antigos devem adotar o header antes da publicação. A idempotência nova cobre **movimentos**; criação de requisições, gastos e outros POSTs não recebeu esse contrato nesta fase. Não apagar chaves automaticamente por TTL, pois isso permitiria repetir movimentos; política de arquivamento precisa preservar a identificação da operação.

## Permissões, sessões e origem

CONTROLES existentes de ADMIN/OPERADOR/CONSULTA foram mantidos. Ajuste de saldo e aprovação de requisição continuam exclusivos de ADMIN. Falha de senha retorna resposta genérica de credenciais; tentativa bloqueada retorna 429 com Retry-After. O bloqueio expira por janela, não é permanente.

Não se confia em X-Forwarded-For ou X-Real-IP. A origem usa o host observado no servidor; a topologia real da proxy ainda precisa de validação antes de configurar proxies confiáveis. Pessoas atrás da mesma proxy podem compartilhar o limite por origem, enquanto a proteção por conta continua global no banco.

Clientes sem Origin/Referer/Fetch Metadata podem usar o contrato explícito de cabeçalho customizado e autenticação normal. Isso preserva ferramentas CLI; o cabeçalho não é uma credencial. Navegadores cross-origin continuam sem CORS permissivo, com cookie SameSite Strict e política de origem. Não se declara imunidade universal a CSRF ou certificação WCAG.

Contadores transitórios guardam hashes de conta/origem e tempo; são removidos após expiração durante autenticações. Eventos de auditoria também usam hashes, que são pseudônimos, não anonimização. Retenção da trilha e resposta a incidentes continuam decisões operacionais.

## Testes executados

- 97 casos SQLite passaram na rodada de integração inicial; depois, 40 casos direcionados de segurança/migração passaram após as ampliações.
- Validação completa SQLite/PostgreSQL 17.11: **196 passed em 38,97 s**, seguida dos **5 novos casos de migração passed em 0,29 s**. A coleta final tem **201 casos**, todos validados. Os cinco casos foram acrescentados depois da coleta da primeira rodada; não se apresentam como uma única execução.
- Um aviso de depreciação Starlette TestClient/httpx permanece, sem falha dos testes.
- `tests/browser_security_smoke.cjs`: resposta perdida depois de commit, retry com mesma chave, alteração de dados, novo modal, double submit, saldo final, refresh de relações, data em São Paulo, contraste, foco, nome do diálogo, clipping e troca/relogin de senha.
- Smokes funcional e PWA existentes executados novamente, com SQLite temporário. A PWA continua sem cache de dados privados e sem fila de operações offline.

Os testes usam schemas/arquivos e pessoas fictícios. O teste de migração compara todas as tabelas legadas antes/depois, testa reaplicação, rollback do DDL, checksum/estrutura e inicialização de produção sem aplicar revisão pendente. O PostgreSQL usado foi local, sem Neon/Render real.

## Aplicação futura em produção — exige autorização

Não publicar esta branch diretamente sobre o serviço atual antes de preparar o banco e os clientes:

1. Revisar código/contratos e identificar o banco/instância corretos. Fazer backup consistente e testar restauração isolada; definir responsável, janela e reversão.
2. Em ambiente administrativo autorizado com acesso ao PostgreSQL, fornecer a conexão somente por configuração segura. Não pressupor shell SSH disponível no Render Free.
3. Executar `python -m app.migrate --check`. Um banco antigo retorna pendente. Este comando não aplica revisão; em SQLite inexistente também não cria o arquivo.
4. Após autorização específica, executar `python -m app.migrate --apply` e repetir `--check`. O apply cria/adiciona as estruturas e registra o checksum atomicamente. Esta ação **não foi executada em produção** nesta etapa.
5. Publicar backend e frontend juntos, conferir `/health`, versão da revisão, login, autorização e movimento de homologação autorizado. Sessões/hashes antigos são preservados, exceto quando uma troca/reset de senha explicitamente os revoga.
6. Rollback de código mantém tabelas aditivas e dados novos. Não remover documentos/chaves/eventos para voltar versão. A versão antiga não garante idempotência, portanto reversão exige restringir/reavaliar operações até corrigir a causa.

No Render e em PostgreSQL remoto, startup com revisão pendente falha com instrução para aplicar explicitamente. SQLite de desenvolvimento e PostgreSQL loopback podem provisionar/migrar automaticamente. Nenhum DDL destrutivo ou migração real foi executado por esta entrega.

## Limites e próximo trabalho

Esta fase fecha os três achados altos reproduzidos e os reforços descritos, com testes. Backups operacionais automáticos, recuperação do último ADMIN, verificação da proxy real, observabilidade de produção, perfis por obra/empresa e ensaio piloto autorizado continuam pendentes. Estoque inicial/NF multitem, paginação/N+1 e novos módulos operacionais pertencem às fases seguintes. Os relatórios da auditoria permanecem como baseline histórico, sem apagar os problemas que documentaram.
