# Publicação temporária no site atual — 8 de novembro de 2026

Solicitação confirmada pelo usuário: atualizar o site atual com o ponto facial desativado. O reconhecimento facial e o modo de demonstração continuam bloqueados no ambiente publicado. Não houve criação de outro site, contratação de plano ou habilitação de biometria real.

- Site: https://compac-almoxarifado.onrender.com
- Conta/workspace Render: a mesma já confirmada nesta conversa, `tea-d8fps3mk1jcs73cr2j2g`.
- Serviço: `srv-dblj286417fc738maoug`, plano Free e deploy automático desligado.
- Commit publicado: `06f388734434204db32c537dfa33932c0a1284e1`, enviado à `main` por fast-forward.
- Deploy: `dep-dbof7ru417fc73837jlg`, estado **live**, finalizado às 19:14:08 de 8/11/2026 em America/Bahia (22:14:08 UTC).
- Versão anterior: `6a24fa763995cc52322b7c618ef9f8b95cbb369d`, deploy `dep-dblj3qlg1s2s73es4dig`.

## Banco e recuperação

Projeto Neon existente `holy-moon-53919999`, banco `compac`, branch `production`/`br-orange-recipe-b63wkhpw`. O banco ainda não tinha `schema_migrations` antes desta publicação.

Criada cópia consistente sem compute: `backup-compac-pre-release-20261108`/`br-still-hill-b64w5nw6`, LSN `0/1C74ED0`. Para ensaiar a atualização sem tocar no banco atual, foi criado o ramo derivado `validacao-compac-release-20261108`/`br-restless-mud-b6o9nl8i`. Os dois ramos permanecem na conta para recuperação/revisão; não foram apagados automaticamente.

As revisões 001–004 foram primeiro aplicadas à cópia de validação. Comparação de contagem e fingerprint do conteúdo das 20 tabelas legadas confirmou preservação integral. Depois, as mesmas revisões foram aplicadas à branch atual em uma única transação, com advisory lock de escrita, limites de lock/statement e verificação de estrutura, PKs, índices, unicidade e checksums. A comparação confirmou o mesmo conteúdo das 20 tabelas antes/depois, inclusive após o deploy. Não houve INSERT/UPDATE/DELETE de dados de negócio, troca de usuário/senha ou recalculação de estoque.

O SQL veio das constantes versionadas em `app/migrations.py` e foi executado pela conexão administrativa do Neon MCP, sem recuperar ou imprimir a senha do banco. Não se afirma execução local da CLI `app.migrate`: nesta publicação, o transporte foi a transação do conector. O [manifesto](evidencias/release-20261108/migration-manifest.json) guarda as instruções não sensíveis e verificações usadas.

## Configuração e aplicação

Foram mescladas, preservando as demais variáveis e segredos, somente configurações não sensíveis: `COMPAC_ENV=production`, `COMPAC_ATTENDANCE_MODE=disabled`, `COMPAC_FACE_SUPERVISED=0`, `COMPAC_REQUIRE_POSTGRES=1` e `COMPAC_COOKIE_SECURE=1`. A atualização pela Render iniciou o deploy; não foi disparado um segundo deploy redundante.

Não foram instalados os opcionais faciais, copiados pesos, salvas fotos ou habilitadas exceções às restrições de produção. A chave do banco e o código de setup existentes foram preservados. A configuração de build continua usando `requirements.lock`, com imports faciais opcionais sob demanda.

## Verificações no site publicado

- Deploy `live`, `/health` 200 e acesso ao banco funcionando.
- `/api/auth/status` 200 e `needs_setup=false`: a conta existente continua cadastrada.
- `/ponto-facial` entrega o shell sem cache; `/api/v1/attendance/terminal/status` retorna 404 com o módulo experimental desativado.
- Estoque e histórico de ponto retornam 401 para visitante sem sessão.
- Nenhum log de aplicação com nível `error` no intervalo consultado após o início do deploy.
- Os assets publicados foram comparados por SHA-256 ao código testado localmente. A suíte anterior passou 623 testes SQLite/PostgreSQL, além dos fluxos locais de navegador.

Resultados HTTP e comparação de assets ficam em [evidências](evidencias/release-20261108/). Não foi efetuado login real, movimentação de homologação ou tratamento de foto no banco atual.

O Chromium automatizado desta sessão recusou a cadeia TLS interceptada pelo proxy do ambiente (`ERR_CERT_AUTHORITY_INVALID`), mesmo após uma tentativa de configurar sua confiança em diretório isolado. Não se ignoraram erros TLS. A verificação HTTP com a CA configurada do ambiente passou; não se apresenta a inspeção visual ao vivo como concluída. Os testes locais de interface já tinham passado antes desta publicação.

## Operação e reversão

Recarregar abas antigas para usar o frontend atualizado: as gravações de estoque desta versão usam o contrato de idempotência já entregue. O ponto continua experimental e desativado no site atual.

Não foi agendada uma reversão automática. Se solicitada, reverter código usando o commit/deploy anterior sem apagar tabelas, autorizações, histórico ou a cópia de recuperação. Voltar ao código anterior retira garantias novas de idempotência; é necessário controlar gravações durante qualquer reversão. Restauração de dados é uma operação separada, não uma consequência automática de rollback do código.

Guias usados: [Render Deploy](https://render.com/docs/deploys), [Render Environment Variables](https://render.com/docs/configure-environment-variables) e [Neon Branching](https://neon.com/docs/introduction/branching). A próxima fase de implementação não deve ser publicada sem uma nova solicitação de implantação.
