# Auditoria de segurança — COMPAC, etapa zero

Referência: 04/11/2026, America/Sao_Paulo. Código-base `6a24fa763995cc52322b7c618ef9f8b95cbb369d`, branch de auditoria `audit/compac-corporativo`. Revisão estática e probes locais em SQLite descartável. Nenhum acesso a banco, usuários, segredos ou configuração de produção. Nenhum arquivo de aplicação alterado.

## Síntese

Não foi identificada uma vulnerabilidade crítica confirmada nesta revisão limitada. Há um achado alto confirmado na proteção contra tentativas de login e lacunas médias de recuperação de credenciais, observabilidade e política de origem. A aplicação já possui controles importantes de senha, cookie, revogação, autorização e integridade; ausência de um recurso corporativo foi distinguida de uma vulnerabilidade explorável.

## Evidência executada

Comando: `.venv/bin/python scripts/audit_security.py`, usando acesso de rede do sandbox somente para permitir o event loop/TestClient funcionar. O script remove `DATABASE_URL`, `COMPAC_TEST_DATABASE_URL`, flags Render e configuração de produção do próprio processo, cria um arquivo SQLite em `TemporaryDirectory` e o remove ao finalizar. Todas as pessoas e credenciais utilizadas são fictícias.

Saída completa em `docs/evidencias/seguranca.json`:

| Probe | Resultado |
|---|---|
| 13 GETs privados sem autenticação | Todos 401 |
| CONSULTA tentando criar categoria ou administrador, ou ler auditoria | Todos 403 |
| Conta CONSULTA lendo `/api/users` | 200; somente active/id/name/role/username, sem hashes |
| Expiração forçada de sessão descartável | `/api/auth/me` retorna 401 |
| Novo login com sessão existente | Token de cookie diferente |
| Cookie local | HttpOnly, SameSite=Strict, Max-Age=28800; Secure é configurado por ambiente |
| 11 tentativas incorretas do mesmo host | Dez 401 e depois 429 |
| 3 ciclos de 9 tentativas erradas no administrador e 1 login correto de outra conta | 27 respostas 401 para o alvo e 3 respostas 200 para a outra conta; nunca 429 |
| 12 tentativas na mesma conta, cada uma de um host diferente | Todas 401; nenhum limite por conta |
| Origin externo ou ausência de `X-Compac-Client: web` | 403 |
| Referer externo, sem Origin, mas com cabeçalho customizado | Criação aceita, 201 |
| Username contendo tentativa simples de SQL injection | 401 |
| Hash armazenado | Sem senha em texto; salt aleatório de 16 bytes e digest de 64 bytes |
| Eventos de falha de login em auditoria | Zero |
| `/openapi.json` público | 200, somente contrato de APIs; nenhuma credencial detectada |

## Achados confirmados

### SEC-01 — Alto — proteção de login incompleta e compartilhada por host

Evidência: `app/main.py:28–29`, `234–255`; `app/serve.py:17`.

O contador é um `defaultdict(deque)` em memória, indexado apenas por `request.client.host`, com dez tentativas em cinco minutos. Um login válido de qualquer usuário remove o contador inteiro daquele host (`login_attempts.pop(host, None)`). O probe demonstrou 27 tentativas erradas contra uma conta sem 429, intercalando a cada nove um login correto de uma conta CONSULTA. O probe distribuído mostrou que a mesma conta não possui um contador compartilhado entre hosts. Reiniciar processo também remove o estado, por construção.

Impacto: resistência incompleta a ataques distribuídos/credential stuffing e possibilidade de um usuário com conta válida reiniciar a proteção para tentar outra conta. Um host também pode impedir temporariamente que outros usuários desse mesmo host façam login.

Risco de implantação, ainda não verificado: o servidor está com `proxy_headers=False`. Se a Render apresentar o mesmo IP da proxy ao aplicativo para diversos visitantes, o bloqueio por host será compartilhado entre usuários legítimos; não foi observado o tráfego real da Render nesta etapa.

Correção recomendada na fase B: persistir limites por conta normalizada e origem em armazenamento compartilhado; não limpar tentativas de uma conta quando outra autentica; usar janelas/atrasos progressivos que não criem bloqueio permanente de conta. Configurar identificação da origem somente a partir das proxies explicitamente confiáveis. Criar testes de reinício, múltiplas origens/contas, sucesso de outra conta e concorrência. Senhas/respostas continuam genéricas.

### SEC-02 — Médio — ciclo de recuperação de credenciais incompleto

Evidência: `app/main.py:234–307`, inventário de rotas. Existe reset de senha apenas via `PATCH /api/users/{key}`, exclusivo de administrador. Não há troca própria com verificação de senha atual nem recuperação com token de uso único/expiração. O próprio administrador pode redefinir a senha, mas precisa estar autenticado.

Impacto confirmado de funcionalidade: perda do acesso do último administrador não possui recuperação pelo aplicativo. Não é bypass de autenticação. Definir uma política operacional de recuperação antes do piloto; decidir canal/identidade e implementar fluxo sem enumeração, com auditoria, expiração e revogação de sessões, preservando compatibilidade dos hashes.

### SEC-03 — Médio — falhas de autenticação não possuem trilha de auditoria

Evidência: `app/main.py:247–255` registra `LOGIN` somente após sucesso. O probe executou dezenas de falhas e encontrou zero evento de falha. O código não possui métrica ou log estruturado equivalente.

Impacto: investigações de tentativa de invasão dependem dos logs HTTP da hospedagem, cuja retenção/configuração não foi inspecionada. Registrar falhas e bloqueios sem senha/token e com minimização/retensão definida de dados pessoais; limitar volume para evitar amplificação de logs. Não inserir a senha ou corpo da requisição no evento.

### SEC-04 — Médio, reforço de defesa — Origin opcional e Referer ignorado

Evidência: `app/main.py:148–165`. Se Origin estiver presente e divergente é recusado; se ausente, Referer não é verificado. O probe com Referer externo e cabeçalho customizado foi aceito.

Não foi demonstrado um CSRF de navegador: o cabeçalho customizado exige preflight cross-origin, não existe CORS permissivo no código, o cliente usa JSON e o cookie é SameSite=Strict. Esses controles atuais fornecem defesa real. A requisição forjada no TestClient não prova que um site externo consegue executá-la no navegador.

Recomendação: documentar explicitamente a estratégia de CSRF e clientes permitidos; validar Origin/Referer quando apropriado e considerar token de sessão/CSRF para operações autenticadas antes de flexibilizar CORS ou integrar origens externas. Criar testes de origem ausente, origem null, subdomínios, esquema/porta e APIs legítimas. Não tratar a ausência de um token CSRF isoladamente como falha crítica.

### SEC-05 — Baixo — contrato OpenAPI continua público

Evidência: `app/main.py:144` desativa docs/redoc, mas mantém a rota padrão `/openapi.json`; probe retorna 200 sem autenticação. A especificação revela estrutura/nomes das operações, sem dados da operação ou credenciais. Não constitui quebra de autorização; decidir conscientemente se a exposição do contrato é desejada e documentar.

### SEC-06 — Baixo — instalação de dependências sem hashes e sem separação de testes

Evidência: `requirements.lock`, `requirements.txt`, `render.yaml`. Versões estão fixadas, mas não há hashes/`--require-hashes`; pytest/httpx e suas dependências são instalados em produção. Recomendação: lock com hashes e conjunto separado de desenvolvimento ao estruturar CI, preservando testes.

## Controles positivos confirmados por código/testes

- Senhas: scrypt com salt aleatório por senha e comparação constante via `hmac.compare_digest`, `app/main.py:94–110`. Mínimo de dez caracteres, máximo 128. Sem formato versionado ou rehash gradual; Argon2id é evolução a avaliar e medir, sem invalidar senhas existentes. O parâmetro atual n=16384/r=8/p=1 merece comparação com a orientação OWASP atual e benchmark da memória/CPU disponível; não foi comprovada quebra do hash.
- Enumeração: usuário inexistente recebe cálculo scrypt dummy e a mesma mensagem 401 usada para senha incorreta, `main.py:248–251`. Não foi feito estudo estatístico de temporização.
- Sessões: token aleatório URL-safe de 32 bytes, somente SHA-256 do token no banco; cookie HttpOnly/SameSite Strict, validade de oito horas e Secure quando `COMPAC_COOKIE_SECURE=1`, `main.py:117–123,208–214`. O Blueprint declara Secure=1. O probe confirmou rotação e rejeição de sessão expirada; a suíte existente testa revogação após mudança de senha, perfil e inativação (`tests/test_workflows.py:313–320`).
- Logout: elimina a sessão corrente no banco e o cookie, `main.py:258–264`. Logins simultâneos criam sessões independentes, sem renovação deslizante ou painel de revogação global.
- Permissões: `current_user`, `operator`, `administrator` no backend; aprovação de requisição, ajuste de saldo e auditoria são restritos a administrador. A proteção não depende de esconder botões, `main.py:117–135,278–307,401–402,520–521,685–688`.
- SQL: valores usam parâmetros; nomes de tabela/coluna dinâmicos são derivados de `ENTITIES`, EXPORTS e relações fixas, não de SQL livre do cliente (`main.py:315–379`, `db.py:89–105`). O probe simples de injeção foi negado; não é um pentest exaustivo.
- XSS: `app/static/app.js:5–16` escapa `&<>\"'` antes de construir HTML de dados; nenhum eval foi encontrado. CSP restringe scripts/estilos/conexões à própria origem e proíbe framing/base/form externas (`main.py:159–164`). A inspeção estática não substitui testes de todos os campos no navegador.
- CSV: prefixa apóstrofo em textos com fórmulas; teste existente percorre exports (`main.py:709–717`, `tests/test_workflows.py:323–343`).
- Erros de integridade: resposta 409 genérica, sem SQL/constraint expostos ao cliente (`main.py:168–171`). Erros operacionais não têm tratamento estruturado próprio; sanitização/retensão dos logs de infraestrutura não foi verificada.
- PWA: service worker ignora APIs e escritas e guarda apenas ativos públicos offline (`app/static/sw.js:1–44`); sem cache de credenciais ou banco no navegador observado.
- TLS PostgreSQL: força verify-full e bundle certifi em conexões remotas, mantendo validação do hostname (`db.py:118–129`); não há fallback silencioso para SQLite quando DATABASE_URL está inválida.

## Autorização horizontal: limite de escopo, sem alegar IDOR confirmado

Todas as contas pertencem à mesma operação e as leituras operacionais são globais. Não há coluna de vínculo usuário→obra/empresa, filtros por proprietário ou múltiplas organizações. OPERADOR pode editar qualquer registro operacional e CONSULTA pode ler inclusive gastos, usuários públicos e exports, conforme controles atuais. Se a política corporativa exigir isolamento por obra/cliente, isso deverá ser especificado e implementado; a ausência de regra ainda não especificada não prova acesso indevido. Não usar esta arquitetura como multiempresa compartilhada sem um projeto de isolamento e testes.

## Dependências

Auditoria independente em `docs/DEPENDENCIAS.md`: 24 versões do lock consultadas no OSV e no PyPI, todas existem e nenhuma fonte retornou advisory conhecido para os pares consultados. Evidências públicas em `docs/evidencias/`. Não foram auditadas imagem/SO da Render, OpenSSL/libpq do wheel ou configuração ao vivo. A ausência de advisory no momento da consulta não garante ausência de vulnerabilidade.

## Pendências para próxima fase

1. Corrigir SEC-01 e expandir testes de autorização/origem antes de aumentar exposição/carga.
2. Política de recuperação/troca de credenciais e trilha minimizada de falhas.
3. Versionar hashes/rehash progressivo; medir Argon2id na infraestrutura prevista.
4. Definir política de autorização por obra e retenção de dados antes de mudanças de alto risco/multiempresa.
5. CI com verificações de dependências, hashes, backup/restauração e testes em PostgreSQL descartável.

Não foram feitas alterações na aplicação, migrações ou publicação. Os testes criados são probes de auditoria preservados em `scripts/`; caberá à implementação converter os casos relevantes em testes permanentes.
