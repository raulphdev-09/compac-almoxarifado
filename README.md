# COMPAC · Almoxarifado

Aplicativo web em português para materiais, estoque por local, empréstimos e devoluções, requisições, chamados, patrimônio, manutenção, gastos, produtividade, previsão de consumo, alertas, exportação CSV e auditoria. Usa FastAPI, PostgreSQL na hospedagem gratuita e SQLite opcional no computador, com quantidades em milésimos, perfis de acesso e sessões de 8 horas. O banco começa vazio: nenhum dado real ou conta padrão acompanha o projeto.

## Atualização de segurança e integridade (branch de desenvolvimento)

A revisão `001_security_integrity` adiciona proteção de reenvio de movimentações, limites de login persistentes e troca própria de senha. Consulte [o relatório e o procedimento de migração](docs/FASE_B_SEGURANCA_INTEGRIDADE.md). No Render/PostgreSQL remoto, uma revisão pendente **não é aplicada automaticamente**: backup/restauração, autorização e `python -m app.migrate --apply` precisam preceder a publicação. O comando `python -m app.migrate --check` consulta o estado.

Clientes de `POST /api/movements` precisam enviar `Idempotency-Key` por operação e reutilizá-la em retry do mesmo conteúdo; a interface desta versão já faz isso. A nova versão ainda não foi publicada em produção. Os testes de navegador da fase estão em `tests/browser_security_smoke.cjs` e usam somente dados descartáveis.

## Ponto experimental — Fase 1

A estrutura de marcações supervisionadas de teste está documentada em [PONTO_FASE_1.md](docs/PONTO_FASE_1.md). Demonstração descartável: `.venv/bin/python scripts/demo_attendance.py`. Não usa câmera, fotografias ou reconhecimento facial real e permanece bloqueada em produção. A revisão aditiva `002_attendance_experimental` exige o procedimento de migração autorizado para bancos remotos; esta branch não foi publicada.

## Terminal experimental — Fase 2

Tela `/ponto-facial` com pré-visualização local da câmera, ativação individual do dispositivo e marcações **simuladas**. Configuração para ADMIN em Gestão de Pessoal → Terminais de ponto · teste. Consulte [execução, migração e limites](docs/PONTO_FASE_2.md) e [validação](docs/evidencias/ponto-fase2-validacao.md). A revisão aditiva `003_attendance_devices` preserva as anteriores; o módulo continua bloqueado em produção. Reconhecimento facial real pertence à Fase 3.

## Comparação facial experimental — Fase 3

OpenCV/YuNet/SFace opcionais, referências autorizadas criptografadas e captura temporária para comparação no servidor, com autorização de uso único vinculada ao dispositivo. Modos `demo` e `facial` separados; produção/Render/banco remoto continuam bloqueados. Consulte [instalação, operação e limites](docs/PONTO_FASE_3.md) e [evidências de testes](docs/evidencias/ponto-fase3-validacao.md). Não há proteção validada contra fotos/vídeos ou homologação como ponto oficial.

## Publicar gratuitamente: Render Free + Neon Free

Esta configuração usa **Render Free para o site** e **Neon Free para guardar os dados em PostgreSQL**. O `render.yaml` não cria serviço pago, disco persistente nem banco pago na Render. Mantenha as duas contas no plano **Free** e respeite os limites desses serviços.

### 1. Criar o banco gratuito

1. Entre em [neon.com](https://neon.com) e crie uma conta no plano **Free** (a página oficial informa que não exige cartão).
2. Crie um projeto, por exemplo `compac-almoxarifado`, e escolha uma região próxima da região do seu site na Render.
3. Abra **Connect** e copie a conexão PostgreSQL mostrada como **Connection string**. A conexão com pooling pode ser usada. Essa URL contém a senha do banco: guarde-a e cole-a somente nas configurações seguras da hospedagem. **Não envie a URL em chat nem faça commit dela.**

### 2. Publicar o site gratuito

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/raulphdev-09/compac-almoxarifado)

1. Abra o botão acima na sua conta da Render e conecte o repositório do GitHub.
2. Confira que o serviço está como **Free**, sem disco pago ou outros recursos pagos. O Blueprint não contrata recursos sozinho.
3. Quando a Render pedir **DATABASE_URL**, cole a conexão copiada do Neon. Essa é uma variável secreta do serviço, não um arquivo do projeto.
4. Para esta revisão, prepare o banco antes da publicação: em ambiente administrativo autorizado, com `DATABASE_URL` em configuração segura, execute `python -m app.migrate --check` e, após backup/autorização, `python -m app.migrate --apply`. Isso não depende de shell no Render Free. Consulte o procedimento da fase B. Depois confirme a criação/publicação e aguarde `/health` ficar saudável.
5. No painel do serviço, abra **Environment** e copie o valor gerado de **COMPAC_SETUP_TOKEN**. Esse é o código de ativação para criar seu primeiro administrador.
6. Abra o endereço **HTTPS** fornecido pela Render, informe o código de ativação e crie seu administrador. O cadastro inicial fica indisponível depois dessa etapa.
7. Cadastre categorias, obras, locais, funcionários e materiais; registre as entradas de estoque. Cada pessoa deve usar sua própria conta e perfil.

Se você já tem dados em um serviço SQLite anterior, preserve e exporte esses dados **antes** de trocar o banco ou remover um disco. Eles não são importados automaticamente para o Neon. Para adaptar um serviço existente, confira a opção **Free**, defina `DATABASE_URL` e `COMPAC_REQUIRE_POSTGRES=1` e só remova o disco antigo após preservar os dados. Alterar o código no GitHub não converte automaticamente um serviço existente.

### Limites e dados

- **Render Free:** o site pode dormir após 15 minutos sem tráfego; a primeira abertura depois disso pode levar cerca de um minuto. Há limites mensais de horas, tráfego e compilações. Isso também afeta a abertura pelo ícone instalado no celular.
- **Neon Free:** armazenamento, transferência e processamento têm cotas. O plano gratuito não é um período de teste, mas é adequado a uso pequeno e deve ter seu consumo acompanhado no painel. As cotas atuais estão na [página oficial de preços](https://neon.com/pricing).
- O filesystem da Render Free é temporário. Todos os dados de operação ficam no Neon; o aplicativo recusa iniciar com `COMPAC_REQUIRE_POSTGRES=1` se `DATABASE_URL` estiver ausente, para evitar guardar dados temporariamente por engano.
- Não use o banco PostgreSQL gratuito da própria Render como substituto permanente: a [documentação oficial](https://render.com/docs/free) informa que ele expira após 30 dias. Esta configuração usa o Neon externo.
- Mantenha cópias de segurança dos dados e acompanhe os avisos de limites dos provedores. A disponibilidade desses planos está sujeita às regras dos serviços.

### Configurações da aplicação

O Blueprint configura `COMPAC_REQUIRE_POSTGRES=1`, `COMPAC_COOKIE_SECURE=1` e `COMPAC_TIMEZONE=America/Sao_Paulo`. O Render informa `PORT` e `RENDER_EXTERNAL_URL`; o aplicativo usa esse endereço externo para verificar a origem das ações. Para domínio próprio, configure `COMPAC_PUBLIC_URL` com a URL HTTPS pública exata. Não use curingas. A ausência do código de ativação impede a inicialização no Render.

As conexões PostgreSQL externas validam o certificado TLS e o nome do servidor. O aplicativo não guarda a senha no código. Uma transação serializa as escritas para manter criação inicial, estoque e atendimento integral de requisições consistentes. PostgreSQL é acessado por conexões curtas, compatíveis com o pooler do Neon.

Publicações automáticas estão desativadas no Blueprint. Depois de revisar uma atualização, use **Manual Deploy** no painel. Nenhuma conta Neon ou serviço Render foi criado por estes arquivos; os dados da conexão devem ser configurados na sua conta para concluir a publicação.

## Executar no computador

Requer Python 3.12. Em um terminal na pasta do projeto:

```sh
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.lock
python -m app.serve
```

Abra `http://localhost:8000`. Sem `DATABASE_URL`, o banco local é criado em `.data/compac.db` (ou no caminho `COMPAC_DB`). Se `DATABASE_URL` estiver definida, a aplicação usa PostgreSQL; use somente um banco de desenvolvimento para testes. Para exigir um código também no ambiente local, configure `COMPAC_SETUP_TOKEN` antes de iniciar. `PORT` permite escolher outra porta. Nunca compartilhe o arquivo do banco ou publique senhas no Git.

Para executar as verificações do projeto:

```sh
.venv/bin/python -m pytest -q
```

A suíte usa SQLite temporário por padrão. Para repetir os mesmos testes em um PostgreSQL **descartável**, forneça uma conexão de teste:

```sh
COMPAC_TEST_DATABASE_URL='postgresql://usuario:senha@servidor/banco_de_teste?sslmode=require' .venv/bin/python -m pytest -q
```

Nunca use uma conexão de produção nesses comandos. Cada caso PostgreSQL cria e remove apenas um schema com nome aleatório, sem tocar os demais schemas. A suíte valida os dois bancos quando essa variável está presente, incluindo concorrência, rollback integral, valores grandes, unicidade e persistência depois de reiniciar a aplicação. Uma URL PostgreSQL inválida ou indisponível não é substituída por SQLite.

Com Node.js e o pacote Playwright disponíveis, `node tests/pwa_smoke.cjs` verifica a PWA em Chromium usando um banco descartável. `PWA_BROWSER_PATH` permite indicar um Chromium instalado no computador. Essa verificação não instala o aplicativo em um celular. `node tests/browser_smoke.cjs` testa os formulários e a navegação com SQLite temporário. Esses scripts ignoram uma `DATABASE_URL` de produção herdada; para o teste funcional com PostgreSQL, use somente `COMPAC_BROWSER_DATABASE_URL` apontando para um banco vazio e descartável.

## Instalar no celular

Use o endereço **HTTPS** da sua implantação e o botão **Instalar aplicativo** do COMPAC.

- **Android / Chrome:** confirme o convite de instalação. Se ele não aparecer, abra o menu **⋮ → Instalar aplicativo** ou **Adicionar à tela inicial**.
- **iPhone / iPad / Safari:** toque em **Compartilhar → Adicionar à Tela de Início → Adicionar**.
- **Computador / Chrome ou Edge:** use o ícone de instalação na barra de endereços ou a opção de instalação no menu.

A instalação oferece um ícone e uma janela própria. **Os dados continuam exigindo conexão com a internet.** Sem rede, o aplicativo mostra uma mensagem amigável e uma página para tentar novamente. Não há cache de APIs ou dados de usuários, nem fila de gravações offline. Só a página pública de indisponibilidade, seus arquivos e os ícones são guardados pelo service worker. Formulários não são recarregados automaticamente quando chega uma atualização: o usuário escolhe quando atualizar.

O manifesto é `/manifest.webmanifest`; o service worker é `/sw.js`, com escopo `/`. Os ícones incluem PNG de 192 e 512 px, uma versão maskable de 512 px com área segura e um ícone Apple de 180 px. Validações automatizadas em Chromium não substituem testes em aparelho real; a instalação em Safari/iPhone precisa ser conferida nesse dispositivo.


## Ferramentas Neon neste projeto

A configuração do Codex em `.codex/config.toml` aponta para o MCP oficial do Neon com OAuth; ela não contém chave de API. A skill `neon-postgres` foi instalada em `.agents/skills/` e sua origem está registrada em `skills-lock.json`.

Destino solicitado para o banco: organização **rauldev** (`org-rough-rain-26686846`), região **São Paulo** e projeto **compac-almoxarifado**. A organização ainda precisa ser acessada com autenticação antes de confirmar ou criar o projeto. Instalar as ferramentas não cria um banco, não publica o site e não preenche `DATABASE_URL` por si só.

A CLI oficial foi instalada fora do repositório, em `/workspace/.tools/neon/node_modules/.bin/neon`. O perfil desta sessão fica fora do Git, em `/workspace/.neon-auth`. Em um agente remoto, use uma chave com acesso à organização por meio da configuração segura `NEON_API_KEY`; nunca cole a chave em mensagens nem a grave nos arquivos versionados. O login OAuth comum da CLI retorna para o localhost da própria máquina e não conecta diretamente um navegador de outra máquina a este ambiente.

Depois de autorizar a CLI, consulte os projetos da organização antes de criar outro, vincule o projeto solicitado e grave as variáveis apenas em `.env` ou `.env.local`, que são ignorados pelo Git. O aplicativo usa variáveis do processo; na Render, configure a conexão no campo `DATABASE_URL` do serviço. Reinicie o agente para carregar o MCP recém-configurado e conclua sua autenticação OAuth se usar esse caminho.
