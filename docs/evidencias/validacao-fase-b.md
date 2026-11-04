# Validação PostgreSQL/SQLite — segurança e integridade

Branch de trabalho: `fix/compac-seguranca-integridade`. Testes executados com PostgreSQL17.11 local descartável, loopback127.0.0.1 porta55439 e banco `compac_audit`. Nenhum acesso a produção.

## Suíte coletada antes das últimas três adições de migração

Comando:

```sh
COMPAC_TEST_DATABASE_URL=postgresql://compac_audit@127.0.0.1:55439/compac_audit .venv/bin/python -m pytest -q
```

Resultado: **196 passed,1warning em38,97s**. Warning: Starlette TestClient/httpx depreciação. A suite inclui os novos testes de troca de senha anônima e rollback da auditoria.

## Incremento adicionado após a coleta inicial

A coleta atual informou **201 testes**. A diferença corresponde a três novos testes de migração, sendo dois parametrizados nos dois bancos e um SQLite:

```sh
COMPAC_TEST_DATABASE_URL=postgresql://compac_audit@127.0.0.1:55439/compac_audit .venv/bin/python -m pytest -q tests/test_migrations.py -k 'test_recorded_migration_requires_primary_key or test_recorded_migration_requires_throttle_indexes or test_check_absent_sqlite_does_not_create_database'
```

Resultado: **5passed,10deselected,1warning em0,29s**.

Total de casos da coleta atual exercitados com sucesso: **201(196+5)**. Nenhuma alteração de app/testes foi feita por esta validação. Cluster temporariamente mantido ligado por coordenação do agente principal.
