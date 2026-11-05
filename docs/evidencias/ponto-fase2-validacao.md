# Validação — ponto experimental, Fase 2

Data: 5 de novembro de 2026. Branch `feat/compac-ponto-fase2`, base `9a7bde1`. Dados fictícios em bancos SQLite temporários e schemas descartáveis de PostgreSQL 17.11 local. Nenhuma conexão de produção, fotografia real ou implantação.

## Suíte automatizada

```sh
COMPAC_TEST_DATABASE_URL=postgresql://compac_audit@127.0.0.1:55439/compac_audit .venv/bin/python -m pytest -q
```

**390 passed, 1 warning em 94,36 segundos**. A URL acima corresponde somente ao servidor descartável desta sessão; para repetir, provisionar PostgreSQL local próprio ou omitir a variável para executar somente SQLite. O aviso conhecido é a depreciação de Starlette TestClient/httpx.

Inclui a suíte anterior de almoxarifado e a Fase 1, além de:

- Quatro tipos de marcação com horário do servidor e resposta sem identificação do trabalhador.
- Ativação de uso único, expiração, cookie restrito/HttpOnly/SameSite/Secure e encerramento da sessão administrativa no navegador ativado.
- Hashes no banco e ausência de segredos nos eventos de auditoria.
- Rotação, terminal revogado, credencial expirada, emissor inativo e obra incorreta.
- Matrícula desconhecida/inativa/outra obra com erro genérico; terminal sem acesso administrativo a cadastros e históricos.
- Rejeição de imagens, booleano facial, obra, terminal e horário enviados indevidamente no corpo.
- Autorização vinculada ao dispositivo, reenvio concorrente, repetição após expiração da autorização e preservação de marcações legítimas próximas.
- Falha de auditoria desfaz marcação/consumo de autorização ou ativação/encerramento de sessão; repetição posterior é possível.
- Tentativas limitadas, produção/Render desabilitados e HTTP não local rejeitado sem consumir código.
- Migração 003 transacional/aditiva; preservação dos checksums 001/002, cadastros e registros da Fase 1; reaplicação, rollback e rejeição de estrutura incompleta.

## Navegador

Chromium com câmera artificial e Playwright, somente servidor/banco local descartável:

```sh
node tests/browser_terminal_smoke.cjs
COMPAC_TEST_ARTIFACTS=/tmp/compac-ponto-fase2-stock-ui COMPAC_TEST_PORT=8838 node tests/browser_smoke.cjs
env -u PWA_BASE_URL PWA_TEST_PORT=8839 node tests/pwa_smoke.cjs
```

- **Terminal PASS:** configuração administrativa pela interface, ativação, pré-visualização da câmera, registro simulado, limpeza automática, resposta perdida seguida de reenvio com a mesma chave, desconexão de rede sem envio automático, câmera negada/ausente, revogação, isolamento dos históricos e ausência de imagens/dados em armazenamento do navegador.
- **Almoxarifado PASS:** configuração inicial, material pelo formulário, entrada de estoque, chamado/comentário/status, telas e navegação desktop/celular sem erros JavaScript.
- **PWA PASS:** instalação Chromium, manifesto/ícones, cache limitado aos recursos públicos, rejeição de GET/POST offline, preservação do formulário, recuperação, ajuda Android/iOS e atualização somente após confirmação explícita.

Capturas inspecionadas de [desktop](ponto-fase2/terminal-desktop.png) e [celular](ponto-fase2/terminal-celular.png), com câmera artificial e obra fictícia, sem código de ativação ou identificação de trabalhador. O roteiro gera as imagens em `artifacts/ponto-fase2/`.

## Limites da evidência

Não foram testados reconhecimento facial real, falsos aceites/rejeições, detecção de rosto, proteção contra fotos/vídeos, câmera física, instalação em obra ou instalação nativa no Safari/iPhone. Nada disso foi apresentado como funcional. Todos os registros têm método de demonstração e resultado **SIMULADO**; não comprovam identidade nem aptidão para ponto oficial.

As mudanças de interface não alteram estoque/saldos e as regressões existentes passaram. Isso comprova os fluxos cobertos pelos testes, sem prometer ausência de qualquer defeito. Publicação e migração de produção permanecem pendentes de uma etapa própria.

Revisão independente somente de leitura do backend: sem bloqueadores encontrados. `git diff --check`, verificação sintática dos novos JavaScripts, compilação dos módulos Python alterados e comparação literal do SQL/checksums 001/002 com a base também passaram.
