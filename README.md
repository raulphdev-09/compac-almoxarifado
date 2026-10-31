# COMPAC · Almoxarifado

Aplicativo web em português para materiais, estoque por local, empréstimos e devoluções, requisições, chamados, patrimônio, manutenção, gastos, produtividade, previsão de consumo, alertas, exportação CSV e auditoria. Usa FastAPI e SQLite, com quantidades em milésimos, perfis de acesso e sessões de 8 horas. O banco começa vazio: nenhum dado real ou conta padrão acompanha o projeto.

## Publicar no Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/raulphdev-09/compac-almoxarifado)

O botão abre o Blueprint do repositório; ele não publica nem contrata recursos sozinho. Revise a configuração e confirme os custos no Render antes de criar os recursos. O `render.yaml` propõe **um serviço Starter pago e um disco persistente de 1 GB**. Consulte os preços atuais no painel: o disco é necessário para preservar o SQLite entre reinícios e publicações. Não troque por armazenamento temporário se precisar manter os dados.

1. Envie o projeto para `raulphdev-09/compac-almoxarifado` no GitHub e abra o botão acima.
2. Conecte o repositório no Render, revise serviço, região, plano e disco e confirme a criação somente após aceitar os custos.
3. Aguarde a implantação ficar saudável. O serviço usa Python 3.12, `requirements.lock`, um processo e a verificação `/health`.
4. No painel do serviço, abra **Environment** e copie o valor gerado de `COMPAC_SETUP_TOKEN`. Ele é o **código de ativação** exigido para criar o primeiro administrador. Não coloque esse código no repositório, em capturas de tela ou em mensagens públicas.
5. Abra o endereço HTTPS fornecido pelo Render. Na configuração inicial, informe o código de ativação e crie seu próprio administrador com senha segura. O cadastro inicial fica indisponível após a criação do primeiro administrador.
6. Cadastre categorias, obras, locais, funcionários e materiais da sua operação e registre o estoque inicial. Cada pessoa deve usar sua própria conta e o perfil adequado.

O Blueprint configura `COMPAC_DB=/var/data/compac.db`, `COMPAC_COOKIE_SECURE=1` e `COMPAC_TIMEZONE=America/Sao_Paulo`. O Render informa `PORT` e `RENDER_EXTERNAL_URL`; o aplicativo usa o endereço externo para verificar a origem das ações. Para domínio próprio, configure `COMPAC_PUBLIC_URL` com a URL HTTPS pública exata (por exemplo, `https://almoxarifado.suaempresa.com.br`). Não use curingas. Em produção no Render, a ausência do código de ativação impede a inicialização.

Publicações automáticas estão desativadas no Blueprint. Depois de revisar uma atualização, use **Manual Deploy** no painel. O disco não substitui uma cópia de segurança: mantenha backups regulares e teste a restauração antes de depender deles. Para copiar um banco em uso, use o backup do SQLite, que gera uma cópia consistente; não copie apenas o arquivo principal enquanto há gravações. O serviço deve continuar com uma única instância e um worker.

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

Abra `http://localhost:8000`. O banco local é criado conforme a configuração do aplicativo. Para exigir um código também no ambiente local, configure `COMPAC_SETUP_TOKEN` antes de iniciar. `PORT` permite escolher outra porta. Nunca compartilhe o arquivo do banco ou publique senhas no Git.

Para executar as verificações do projeto:

```sh
.venv/bin/python -m pytest -q
```

Com Node.js e o pacote Playwright disponíveis, `node tests/pwa_smoke.cjs` verifica a PWA em Chromium usando um banco descartável. `PWA_BROWSER_PATH` permite indicar um Chromium instalado no computador. Essa verificação não instala o aplicativo em um celular.

## Instalar no celular

Use o endereço **HTTPS** da sua implantação e o botão **Instalar aplicativo** do COMPAC.

- **Android / Chrome:** confirme o convite de instalação. Se ele não aparecer, abra o menu **⋮ → Instalar aplicativo** ou **Adicionar à tela inicial**.
- **iPhone / iPad / Safari:** toque em **Compartilhar → Adicionar à Tela de Início → Adicionar**.
- **Computador / Chrome ou Edge:** use o ícone de instalação na barra de endereços ou a opção de instalação no menu.

A instalação oferece um ícone e uma janela própria. **Os dados continuam exigindo conexão com a internet.** Sem rede, o aplicativo mostra uma mensagem amigável e uma página para tentar novamente. Não há cache de APIs ou dados de usuários, nem fila de gravações offline. Só a página pública de indisponibilidade, seus arquivos e os ícones são guardados pelo service worker. Formulários não são recarregados automaticamente quando chega uma atualização: o usuário escolhe quando atualizar.

O manifesto é `/manifest.webmanifest`; o service worker é `/sw.js`, com escopo `/`. Os ícones incluem PNG de 192 e 512 px, uma versão maskable de 512 px com área segura e um ícone Apple de 180 px. Validações automatizadas em Chromium não substituem testes em aparelho real; a instalação em Safari/iPhone precisa ser conferida nesse dispositivo.
