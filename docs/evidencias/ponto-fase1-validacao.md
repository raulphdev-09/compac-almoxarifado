# Validação — ponto experimental, Fase 1

Data: 5 de novembro de 2026. Branch `feat/compac-ponto-fase1`, base `8c1aab1`. Somente dados fictícios em SQLite temporário e PostgreSQL 17.11 local, com schemas descartáveis. Nenhum acesso a imagens, banco ou usuários reais.

## Suíte completa nos dois motores

```sh
COMPAC_TEST_DATABASE_URL=postgresql://compac_audit@127.0.0.1:55439/compac_audit .venv/bin/python -m pytest -q
```

Resultado: **311 passed, 1 warning em 61,32 segundos**. Aviso conhecido: depreciação Starlette TestClient/httpx. Inclui regressões anteriores de almoxarifado, credenciais/sessões, permissões, idempotência, concorrência, migrações e novos testes do ponto experimental.

Rodadas direcionadas: 33 casos de ponto passaram em SQLite antes da adição do teste final de reinicialização, e 58 casos de migração passaram em ambos os motores. A suíte completa posterior inclui essas ampliações; os totais direcionados não são somados aos 311.

## Navegador e demonstração

```sh
COMPAC_TEST_ARTIFACTS=/tmp/compac-ponto-fase1-ui COMPAC_TEST_PORT=8836 node tests/browser_smoke.cjs
.venv/bin/python scripts/demo_attendance.py
```

Teste de navegador: **PASS**, cadastro inicial, material, entrada de estoque, chamados/comentários/status e navegação desktop/mobile sem erro JavaScript.

Demonstração: quatro registros com UID exclusivo, horário do servidor, tipo de marcação e `verification_result=SIMULADO`; cada pedido foi reenviado com a mesma chave e preservou seu ID. Banco temporário removido ao final. Não imprime senhas nem autorizações temporárias.

## Controles comprovados pelos testes

- Modo desabilitado por padrão e em produção/Render/banco remoto.
- ADMIN exclusivo; sessão, funcionário/obra/terminal e revogação revalidados.
- Nenhum booleano facial, horário, foto ou obra do cliente aceito em `/mark`.
- Autorizações com hash, validade e uso único; reenvio concorrente confirma apenas um registro.
- Marcas legítimas próximas permanecem separadas; originais sem endpoint de alteração/exclusão.
- Falha de auditoria ou HTTP após INSERT não deixa marcação/token parcialmente confirmado.
- Limites de tentativas persistem sem criar autorizações indevidas.
- Migração 001 preservada; 002 aditiva, reaplicável e transacional, com testes de FK/uniqueness/checksums/rollback e preservação de dados anteriores.

Não foram testados câmera, reconhecimento facial real, antiapresentação de fotos/vídeos, instalação física de terminal, cálculo oficial de jornada ou homologação legal. Esses componentes não fazem parte da Fase 1. Os testes não comprovam aptidão do protótipo para substituir o ponto oficial.
