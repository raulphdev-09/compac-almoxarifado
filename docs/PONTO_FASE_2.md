# COMPAC — terminal experimental, Fase 2

Branch `feat/compac-ponto-fase2`, baseada em `9a7bde1`, conclusão da Fase 1. Entrega da interface de terminal, câmera local e credenciais de dispositivos, com marcações supervisionadas **SIMULADAS**. Não há comparação facial, detecção de rosto ou confirmação biométrica. Nenhum banco, configuração ou serviço de produção foi alterado.

## Auditoria antes das alterações

O projeto mantém FastAPI, SQLite/PostgreSQL, HTML/CSS/JavaScript e PWA. A Fase 1 já oferece terminais associados a `works`, funcionários em `employees`, autorizações temporárias e registros de teste auditados. As marcações usam horário do servidor, idempotência, transação de escrita e validações de funcionário/obra/terminal. As APIs existentes de administração e histórico exigem ADMIN.

Faltavam a tela `/ponto-facial`, acesso à câmera e uma credencial restrita ao dispositivo: usar a sessão administrativa no terminal compartilhado permitiria consultar outros cadastros. Esta entrega cria um acesso próprio, sem duplicar funcionários/obras nem modificar saldos, empréstimos ou movimentos do almoxarifado. FICC, PRAÇA e TRANSBORDO são selecionadas do cadastro existente quando disponíveis; nenhuma obra é inserida automaticamente.

## Funcionamento e limites

- ADMIN cria um terminal vinculado a uma obra e emite um código de ativação, de uso único e validade de dez minutos. O código aparece somente nessa resposta, mascarado na interface; não entra em URL ou armazenamento local.
- O dispositivo troca esse código por um cookie HttpOnly, SameSite Strict, restrito ao caminho da API do terminal e válido por doze horas. Somente hashes dos códigos/credenciais ficam no banco. Ativação encerra a sessão administrativa existente naquele navegador.
- Cada emissão de novo código invalida os códigos e acessos anteriores daquele terminal. Revogação, expiração, administrador emissor inativo/sem função ADMIN, obra indisponível ou terminal revogado impedem novas marcações, inclusive reenvios.
- O terminal exibe somente sua obra/nome, relógio sincronizado com o servidor e confirmação mínima. Não fornece lista de funcionários nem histórico. Matrículas inexistentes, inativas ou de outra obra recebem o mesmo erro genérico.
- A câmera abre após ação do usuário. O vídeo é uma pré-visualização local: não há captura, envio ou persistência de quadros, fotografias ou vetores. Ver um rosto não comprova identidade; toda marcação depende de confirmação explícita do supervisor e dados fictícios.
- Entrada, início/retorno de intervalo e saída são escolhas explícitas. Não se deduz escala, jornada, atraso ou falta. O horário persistido vem do servidor; obra/terminal vêm da credencial validada no backend.
- Autorização de teste dura sessenta segundos, tem uso único e fica vinculada ao dispositivo. A marcação usa a idempotência transacional existente. Reenvios do mesmo pedido retornam o mesmo registro; pedidos legítimos diferentes, mesmo próximos, continuam separados.
- Após sucesso, matrícula e confirmação do supervisor são apagadas e a tela retorna ao início. Erros de câmera, falta de dispositivo, rede indisponível e acesso revogado apresentam orientação.
- Sem internet não há fila nem envio automático. Se a resposta se perder, a tentativa fica somente na memória da página; o botão repete a mesma chave/conteúdo. Antes de encerrar uma tentativa incerta ou recarregar a página, o supervisor deve conferir o histórico administrativo. Encerrar a tentativa não apaga registros.

As gravações revalidam permissões dentro da transação. Limites de tentativas persistem no banco; falha de auditoria ou regra de negócio desfaz os efeitos parciais. A proteção existente contra requisições de outra origem continua aplicada. HTML e APIs do terminal usam `no-store`; a PWA não passa a armazenar dados de ponto ou enviar marcações offline.

As quotas de teste podem ser compartilhadas por dispositivos do mesmo emissor e por conexões vistas com a mesma origem atrás de um proxy. O módulo não confia em `X-Forwarded-For` enviado pelo cliente. Dimensionamento e identificação confiável da origem precisam ser revistos antes de um teste com vários terminais.

## Arquivos criados

| Arquivo | Função |
| --- | --- |
| `app/attendance/device.py` | Ativação, credenciais restritas, autorização vinculada ao dispositivo, marcação mínima, limites e logout |
| `app/static/attendance-admin.html`, `.css`, `.js` | Administração de terminais, obras existentes, código temporário, rotação e revogação |
| `app/static/attendance-terminal.html`, `.css`, `.js` | Interface responsiva, câmera local, quatro tipos de marcação, confirmação e recuperação de rede |
| `tests/test_attendance_devices.py` | Segurança, autorização, isolamento, idempotência, simultaneidade e rollback das APIs |
| `tests/test_attendance_device_migrations.py` | Migração aditiva, preservação de dados/checksums, rollback e detecção de estrutura incompleta |
| `tests/test_attendance_terminal_pages.py` | Permissões das páginas, cabeçalhos e ausência de persistência/captura de imagens |
| `tests/browser_terminal_smoke.cjs` | Fluxo administrativo/terminal, câmera artificial, rede, reenvio, revogação e telas desktop/celular |
| `docs/PONTO_FASE_2.md`, `docs/evidencias/ponto-fase2-validacao.md` | Uso, plano de migração, resultados e limites desta fase |
| `docs/evidencias/ponto-fase2/terminal-desktop.png`, `terminal-celular.png` | Capturas com obra fictícia e câmera artificial, sem códigos ou trabalhadores |

## Arquivos alterados

| Arquivo | Alteração |
| --- | --- |
| `app/migrations.py` | Acrescenta revisão 003 e validação estrutural, mantendo SQL/checksums 001 e 002 |
| `app/attendance/routes.py` | Metadados do módulo indicam Fase 2 e suporte à autenticação do terminal |
| `app/main.py` | Registra APIs/páginas; restringe câmera à própria origem e impede cache das páginas |
| `app/static/app.js` | Link administrativo em Gestão de Pessoal |
| `tests/test_migrations.py`, `tests/test_attendance_migrations.py` | Adequa regressões à cadeia de três revisões sem remover verificações anteriores |
| `README.md` | Liga documentação e evidências da Fase 2 |

## Migração segura

`003_attendance_devices` acrescenta somente três tabelas: `attendance_activation_codes`, `attendance_device_sessions` e `attendance_device_authorizations`, com chaves estrangeiras, unicidade e índices. Não altera tabelas de funcionários, obras, estoque ou registros originais. O SQL e os checksums das revisões 001 e 002 continuam iguais.

O runner existente aplica a revisão em transação, verifica a sequência/checksums e recusa estrutura incompatível. Os testes partem da revisão 002 com marcações/cadastros preenchidos, atualizam para 003, repetem a execução e conferem os dados. Erro na aplicação desfaz integralmente a nova revisão.

SQLite e PostgreSQL local de desenvolvimento podem aplicar migrações pelo fluxo existente. Bancos remotos e Render continuam exigindo migração administrativa explícita. Para uma futura implantação autorizada: fazer backup verificável, executar `python -m app.migrate --check`, revisar a revisão pendente, executar `python -m app.migrate --apply` e conferir novamente `--check` antes da publicação. Nenhum desses comandos foi executado contra produção nesta entrega; não usar rollback destrutivo para desfazer a aplicação.

## Executar localmente

Com as dependências do projeto instaladas, use banco descartável e nenhuma conexão remota herdada:

```sh
env -u DATABASE_URL -u COMPAC_REQUIRE_POSTGRES -u RENDER -u COMPAC_PUBLIC_URL -u RENDER_EXTERNAL_URL -u COMPAC_SETUP_TOKEN COMPAC_COOKIE_SECURE=0 COMPAC_DB=/tmp/compac-ponto-fase2-demo.db COMPAC_ENV=development COMPAC_ATTENDANCE_MODE=demo .venv/bin/python -m app.serve
```

1. Abra `http://localhost:8000`. Crie uma conta administrativa de teste e cadastre obra e funcionário fictícios com matrícula, obra e situação ativa.
2. Entre em Gestão de Pessoal → Terminais de ponto · teste, ou `/ponto-facial/configuracao`. Cadastre o terminal e selecione a obra existente.
3. Gere um código. Em outro perfil/navegador, abra `/ponto-facial` e informe o código. A ativação encerra qualquer sessão administrativa daquele perfil.
4. Ative a câmera e permita o acesso. Informe a matrícula fictícia, escolha a marcação e confirme a supervisão. O resultado será **SIMULADO**.
5. O histórico continua disponível somente nas APIs administrativas da Fase 1; por exemplo, `GET /api/v1/attendance/records` com a sessão ADMIN. O dashboard de ponto e seus relatórios pertencem à Fase 4.

Não há nova dependência de reconhecimento facial. O módulo exige `COMPAC_ATTENDANCE_MODE=demo` e `COMPAC_ENV=development` ou `test`, e recusa Render, produção e PostgreSQL remoto. A câmera e a API de dispositivos exigem HTTPS fora de localhost; HTTP é aceito somente quando o host da URL e o endereço de conexão são locais. Para um proxy TLS confiável em ambiente de teste, configurar no servidor `COMPAC_PUBLIC_URL=https://...` e `COMPAC_COOKIE_SECURE=1`; cabeçalhos de encaminhamento enviados pelo cliente não habilitam essa exceção. Servir em HTTPS não remove as demais restrições do modo experimental.

## Testes e pendências

A suíte completa passou **390 testes em SQLite e PostgreSQL local**. Passaram também os testes de navegador do novo terminal, dos fluxos anteriores do almoxarifado e da PWA. Comandos, cobertura e evidências estão em [ponto-fase2-validacao.md](evidencias/ponto-fase2-validacao.md).

Testes de câmera usaram dispositivo artificial do Chromium, sem imagens reais. Câmera física, permissões específicas de Safari/iOS e instalação em tablet de obra ainda precisam de validação. A pré-visualização não identifica ninguém e não oferece proteção contra fotos/vídeos. Não existe modo biométrico funcional nesta entrega.

Fase 3: escolher e avaliar biblioteca/licença, referência autorizada protegida, comparação real, falsos aceites/rejeições e proteção contra apresentação de fotos/vídeos. Fase 4: dashboard, escalas, relatórios e ajustes auditados. Importação de materiais/documentos, relatórios PDF/WhatsApp e o trabalho separado de performance não foram incluídos nesta fase.

O protótipo não é homologado e não substitui o procedimento oficial de ponto. Uso oficial exige avaliação trabalhista brasileira, integridade/comprovantes/exportações e regras de escala/folgas/feriados/justificativas. Antes de tratar fotografias reais, são necessários autorização organizacional, base legal apropriada para dados biométricos sensíveis, controle de acesso, retenção/exclusão e alternativa sem biometria, conforme LGPD e avaliação dos responsáveis. Nenhuma foto de empregado foi processada.
