# COMPAC — ponto experimental, Fase 1

Branch: `feat/compac-ponto-fase1`, baseada na versão de segurança `8c1aab1`. Entrega de estrutura, persistência e APIs de teste supervisionado. **Não há reconhecimento facial real, câmera ou ponto oficial nesta fase.** Nenhum dado ou recurso de produção foi alterado.

## Auditoria inicial

O projeto usa FastAPI, SQLite/PostgreSQL, HTML/CSS/JavaScript e PWA. `employees` já possui matrícula, nome, cargo, obra e situação; `works` já representa as obras. A autenticação existente usa sessões, ADMIN/OPERADOR/CONSULTA e auditoria transacional. Antes desta entrega não havia módulo de presença/ponto nem tabelas de fotos de referência.

Reutilizados os cadastros e os controles existentes. FICC, PRAÇA e TRANSBORDO não são criadas automaticamente: o administrador escolhe uma obra já cadastrada, e o backend usa seu ID. As migrações não semeiam pessoas, contas ou obras reais.

O trabalho anterior de performance está preservado em `perf/compac-fase-c`, commit de progresso `f07e3c5`; não foi incorporado como funcionalidade concluída nesta entrega. Por escolha do usuário, importação de documentos e relatórios PDF ficam para o próximo bloco.

## Implementado

- Estrutura isolada `app/attendance/`: schemas estritos, serviço e rotas.
- Migração aditiva `002_attendance_experimental`: terminais de teste, autorizações temporárias e marcações, com FKs, unicidade e índices. O texto e o checksum da revisão 001 foram preservados.
- Os quatro tipos: ENTRADA, INICIO_INTERVALO, RETORNO_INTERVALO e SAIDA. Não se impõe ordem ou intervalo mínimo entre marcações legítimas.
- Horário UTC fornecido pelo servidor; obra derivada do terminal cadastrado; funcionário ativo e vinculado àquela obra, revalidado na marcação.
- Autorização de demonstração válida por 60 segundos, vinculada ao funcionário, terminal e administrador emissor. Só seu SHA-256 fica no banco; uso único confirmado na transação da marcação.
- Header Idempotency-Key obrigatório em `/mark`; reenvio idêntico retorna o registro original. Outra intenção exige outra autorização/chave. Chave reaproveitada com outro conteúdo retorna 409.
- Todas as marcações são `is_test=1`, `verification_method=DEMO_SUPERVISIONADO`, `verification_result=SIMULADO`. Não há campo que aceite `face_verified=true` como prova.
- Histórico paginado/filtros e auditoria sem fotos, vetores ou tokens de autorização. Registros não expõem o hash interno da autorização.
- Permissão exclusiva de ADMIN nesta fase, com sessão revalidada sob a transação nas gravações. Não há autenticação de dispositivo nem acesso público de trabalhador.
- Limite persistente de 30 tentativas por administrador/origem de terminal em cinco minutos. Tentativas recusadas não deixam efeitos parciais de negócio. A marcação, consumo da autorização, auditoria e idempotência são atômicos.

## APIs

Arquivos criados: `app/attendance/__init__.py` delimita o módulo; `schemas.py` valida os contratos; `service.py` concentra as regras; `routes.py` protege e expõe as APIs. `scripts/demo_attendance.py` executa a demonstração descartável. `tests/test_attendance.py` e `tests/test_attendance_migrations.py` cobrem o módulo e a migração. Este documento e a evidência de validação registram escopo/resultados.

Arquivos alterados: `app/main.py` somente registra as novas rotas; `app/migrations.py` passa a aplicar as revisões ordenadas e adiciona a 002; `tests/test_migrations.py` acompanha o novo histórico de revisões; `README.md` aponta para a execução e os limites. Nenhum arquivo da interface ou regra de estoque foi alterado nesta branch.

Todas exigem a sessão administrativa existente. Escritas mantêm o cabeçalho `X-Compac-Client: web` e os controles de origem do COMPAC.

| Método/caminho em `/api/v1/attendance` | Função |
|---|---|
| GET `/status` | Informa fase, modo, reconhecimento facial falso e autenticação de terminal ainda ausente |
| POST/GET `/terminals` | Cadastra/lista terminais de teste vinculados a uma obra existente |
| POST `/terminals/{id}/revoke` | Revoga o terminal e impede uso de autorizações pendentes |
| POST `/test-authorizations` | Matrícula, terminal e acknowledgement exato `TESTE_SUPERVISIONADO`; gera autorização temporária de demonstração |
| POST `/mark` | Recebe somente authorization e mark_type, com Idempotency-Key; registra horário/obra pelo servidor |
| GET `/records` | Filtros employee_id, work_id, mark_type, date_from, date_to; limit 1–100 e offset até 100.000 |
| GET `/employee/{id}` e `/worksite/{id}` | Histórico paginado por funcionário/obra, ainda restrito ao administrador |

Filtros de dia usam `COMPAC_TIMEZONE` (padrão America/Sao_Paulo); instantes são armazenados em UTC. Não há exportação de ponto nem cálculo de horas, atraso ou falta nesta fase.

## Executar uma demonstração descartável

Na raiz do repositório, com as dependências existentes instaladas:

```sh
.venv/bin/python scripts/demo_attendance.py
```

O script limpa os alvos herdados de produção **somente no próprio processo**, cria SQLite temporário, administrador/obra/funcionário fictícios e quatro marcações simuladas. Repete cada pedido com a mesma chave para conferir a proteção de reenvio, imprime resultados sem autorização/senha e remove o banco no final. Não abre câmera e não usa fotos.

Para desenvolvimento HTTP local, use um arquivo SQLite exclusivo de demonstração:

```sh
COMPAC_DB=/tmp/compac-ponto-desenvolvimento.db COMPAC_ENV=development COMPAC_ATTENDANCE_MODE=demo .venv/bin/python -m app.serve
```

Abra `http://localhost:8000`, crie a conta de demonstração e use os cadastros existentes com pessoas/obras fictícias. As APIs acima estão no contrato `/openapi.json`; a tela `/ponto-facial` e o terminal com câmera pertencem à Fase 2, não foram entregues como interface pronta.

Sem `COMPAC_ATTENDANCE_MODE=demo` **e** `COMPAC_ENV=test|development`, o módulo fica desativado. `RENDER=true`, ambiente de produção e banco PostgreSQL remoto bloqueiam a demonstração mesmo que o modo demo esteja configurado. O status administrativo continua informando a indisponibilidade. Não alterar essas proteções para testar no sistema real.

## Migração e preservação

O runner passou a suportar revisões ordenadas. Confere checksums antigos/novos, recusa gaps/revisões desconhecidas e valida estrutura e unicidade esperadas. A revisão 002 só adiciona tabelas/índices; não altera saldos, funcionários, obras ou movimentos históricos. Em falha, DDL e registro da revisão fazem rollback; a revisão 001 já aplicada permanece intacta.

No Render/PostgreSQL remoto, revisão pendente continua exigindo aplicação administrativa explícita, depois de backup/restauração e autorização. Nenhuma migração de produção foi executada nesta entrega. Se no futuro houver rollback de código, preservar tabelas e registros novos; não limpar histórico para voltar versão.

O aplicativo não tem rota para editar/apagar marcações originais. Ajustes administrativos rastreáveis serão projetados na Fase 4. Isto não é garantia contra alguém com acesso administrativo direto ao banco: controle de acesso, backup e procedimento de auditoria continuam necessários.

## Testes e limites

Testes usam apenas dados fictícios e bancos/schemas descartáveis. Cobrem quatro tipos, horário do servidor, permissões, bloqueio em produção, funcionário/obra/terminal, token hash/validade/uso único, reenvio sequencial e concorrente, marcações próximas legítimas, rollback após falha e persistência após reinicialização. Migrações cobrem upgrade de 001, preservação de dados, reaplicação, checksum, rollback, constraints e unicidade.

Resultado consolidado está em `docs/evidencias/ponto-fase1-validacao.md`. A suíte anterior do almoxarifado permanece incluída na validação. Há um aviso de depreciação Starlette TestClient/httpx já conhecido.

Ainda não se aplicam testes de ausência/múltiplos rostos, identidade facial, câmera ou falha de rede do terminal: esses componentes não existem na Fase 1. Não foram usados rostos sintéticos aprovados por um comparador fictício nem fotos reais. Todos os resultados positivos de verificação são explicitamente **simulações supervisionadas**, restritas ao modo local de teste.

## Próximas fases e uso oficial

Fase 2: `/ponto-facial`, câmera, credenciais individuais por dispositivo, vínculo seguro à obra e isolamento do terminal compartilhado. Fase 3: avaliar biblioteca/licença/compatibilidade, foto autorizada protegida, verificação real e falsos aceites/rejeições; documentar apresentação de foto/vídeo e restringir a testes supervisionados enquanto não houver proteção validada. Fase 4: gestão, escalas, relatórios e ajustes; Fase 5: qualidade e implantação autorizada.

O protótipo não é homologado e não substitui o ponto oficial durante testes. Antes de eventual uso oficial, a organização deve validar o enquadramento e requisitos trabalhistas brasileiros de registro de jornada (integridade, comprovantes, exportações e fiscalização), além das políticas de escala, folgas/feriados e justificativas. Ausência de marcação não é falta automática.

Reconhecimento facial implica tratamento de dado biométrico sensível: exige finalidade/base legal apropriada, autorização organizacional, minimização, segurança, acesso, retenção/exclusão e alternativa sem biometria, conforme avaliação dos responsáveis por LGPD/jurídico. Nenhuma foto real de empregado foi solicitada, processada ou armazenada nesta fase. Esses requisitos não são satisfeitos apenas por ativar uma biblioteca ou um checkbox.
