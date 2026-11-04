# PostgreSQL local — evidências da Etapa Zero

Data: 2026-11-04. Código de referência: `6a24fa7`. Nenhum recurso Neon, Render, banco remoto ou credencial de produção foi consultado. Todos os testes usaram dados fictícios no loopback.

## Ambiente disponibilizado

PostgreSQL **17.11 (Debian 17.11-0+deb13u1)**, extraindo pacotes públicos Debian em `/tmp/compac-pg/root`; nenhuma instalação em `/usr` ou alteração de `.venv`.

Fontes: `https://deb.debian.org/debian/pool/main/p/postgresql-17/`:

- `postgresql-17_17.11-0+deb13u1_amd64.deb`: SHA256 `d2ce1ddffafa783f9acda4c92c86fc21e8288bff3782d739294f14fa797d7886`.
- `postgresql-client-17_17.11-0+deb13u1_amd64.deb`: SHA256 `9d8558f8dd57c8e92e218a20698383575d53742ca3f9e7c2b7fe5f246d5216ae`.

Cluster `/tmp/compac-pg/data`, `listen_addresses=127.0.0.1`, porta **55439**, Unix socket `/tmp/compac-pg`. Database `compac_audit`, role fictícia `compac_audit`; `trust` restrito ao loopback e socket descartáveis. Esse mecanismo não deve ser usado numa hospedagem de produção.

Preparação reproduzível, após baixar e extrair os dois pacotes com `dpkg-deb -x`:

```sh
/tmp/compac-pg/root/usr/lib/postgresql/17/bin/initdb -D /tmp/compac-pg/data -L /tmp/compac-pg/root/usr/share/postgresql/17 --locale=C.UTF-8 -E UTF8 --auth-local=trust --auth-host=trust -U compac_audit
/tmp/compac-pg/root/usr/lib/postgresql/17/bin/pg_ctl -D /tmp/compac-pg/data -l /tmp/compac-pg/server.log -o '-p 55439 -h 127.0.0.1 -k /tmp/compac-pg' start
/tmp/compac-pg/root/usr/lib/postgresql/17/bin/createdb -h 127.0.0.1 -p 55439 -U compac_audit compac_audit
```

## Suíte existente nos dois bancos

```sh
COMPAC_TEST_DATABASE_URL=postgresql://compac_audit@127.0.0.1:55439/compac_audit .venv/bin/python -m pytest -q
```

**50 passed, 1 warning em 7,15 s**. O warning é depreciação Starlette TestClient/httpx. Fixtures criam schemas aleatórios e os removem ao fim (`tests/conftest.py:16–60`). Resultado confirma as regressões existentes com SQLite e PostgreSQL; não demonstra cobertura de requisitos ainda ausentes. PostgreSQL local não testa TLS externo, pooler Neon, região, cold start ou as configurações da produção.

## EXPLAIN ANALYZE

Transcrição do script em `docs/evidencias/postgresql/explain_benchmark.py.txt`, saída `docs/evidencias/postgresql/explain-summary.json`, planos completos `100-*.json`, `1000-*.json`, `10000-*.json`. Script tem DSN local fixo e opera só schemas `compac_bench_*` descartáveis.

Três cenários: 100 / 1.000 / 10.000 movimentos, 50 materiais, uma localização/obra/funcionário/usuário fictícios, N empréstimos (metade abertos), N/10 requisições de 10 itens, N/10 despesas. Semear por SQL mede volume, não simula a coerência operacional de cada empréstimo. `ANALYZE` antes das consultas; uma execução de aquecimento e uma de medição por consulta.

Tempos são **Execution Time do PostgreSQL em ms**, sem serialização de JSON nem rede de longa distância:

| Consulta real | 100 movimentos | 1.000 | 10.000 |
|---|---:|---:|---:|
| Histórico completo (`main.py:460`) | 0,152 | 1,118 | 14,993 |
| Empréstimos abertos (`main.py:476`) | 0,071 | 0,411 | 4,009 |
| Itens de uma requisição (`main.py:484`) | 0,024 | 0,082 | 0,436 |
| Estoque por localização (`main.py:464`) | 0,074 | 0,094 | 0,073 |
| Despesas por obra (`main.py:670`) | 0,028 | 0,061 | 0,396 |

**Achado confirmado, médio:** consulta de itens da requisição usa `Seq Scan requisition_items`, retornando 10 e descartando 90 / 990 / 9.990 linhas. Não há índice `requisition_items(requisition_id)` no esquema. O endpoint executa uma consulta de itens para cada requisição. Recomendar eliminar N+1, paginar e só depois medir índice adequado. `Seq Scan` em pequenas dimensões ou ao retornar a tabela inteira é uma escolha legítima, não bug por si só.

## Latência da API PostgreSQL quente, dados fictícios

Transcrição do script em `docs/evidencias/postgresql/api_benchmark.py.txt`, evidência `docs/evidencias/postgresql/api-summary.json`. 20 amostras sequenciais após aquecimento, cliente ASGI TestClient no mesmo ambiente, sem rede pública, com consulta real a PostgreSQL via TCP loopback. Inclui autenticação, abertura de conexões, SQL, conversão e serialização; não é tempo exclusivamente de SQL nem medição isolada no servidor. p95 nearest-rank = 19ª amostra ordenada, p99 = 20ª. Com 20 amostras, as caudas são apenas indicativas.

| Movimentos | Endpoint | p50 ms | p95 ms | p99 ms | SQL/requisição | Bytes JSON |
|---:|---|---:|---:|---:|---:|---:|
|100|`/api/movements`|10,142|11,077|11,084|2|31.857|
|100|`/api/requisitions`|10,035|10,642|10,956|12|12.498|
|100|`/api/dashboard`|9,765|10,135|11,395|11|992|
|1.000|`/api/movements`|32,474|35,233|35,437|2|319.534|
|1.000|`/api/requisitions`|43,280|54,343|65,820|102|126.846|
|1.000|`/api/dashboard`|9,262|11,253|12,419|11|1.002|
|10.000|`/api/movements`|269,886|450,937|512,301|2|3.205.295|
|10.000|`/api/requisitions`|649,361|707,301|720,669|1.002|1.289.118|
|10.000|`/api/dashboard`|12,000|13,239|13,974|11|1.012|

**Achados confirmados, médio:** histórico cresce sem paginação, resposta de 3,2 MB com 10k movimentos; requisições mostram N+1 mensurado (1.002 SQLs com 1.000 requisições/10.000 itens). Esses cenários ultrapassam 300 ms de p95 do percurso cliente/aplicação local, não autorizando afirmar SLA de servidor/produção reprovado. A rede Render–Neon pode amplificar N+1; a magnitude real não foi medida.

## Backup/restauração descartável testado

Transcrição do script em `docs/evidencias/postgresql/restore_smoke.py.txt`. Executado `pg_dump -Fc --no-owner`, criado banco LOCAL `compac_restored`, executado `pg_restore --no-owner --exit-on-error`. Comparação entre origem e destino: SHA256 de linhas canonizadas por tabela, contagem de linhas, `last_value` e `is_called` de sequências, total de constraints e índices.

**PASS: 60 tabelas, 54 sequências de identidade, 210 constraints e 111 índices.** Dump sintético 321.215 bytes. Evidência `docs/evidencias/postgresql/restore-result.json`. O dump foi feito antes do benchmark de API inserir sessões sintéticas, por isso representa o ponto original das bases de benchmark.

Este ensaio prova a restauração local desses dados fictícios. Não cria uma política de backups no produto, não verifica backups reais, retenção, cifragem, RPO/RTO ou restauração do ambiente Render/Neon. Automatização e runbook continuam pendentes.

## Limitações e encerramento

- Nenhuma otimização, alteração de schema da aplicação ou migração foi implementada nesta tarefa.
- Sem testes distribuídos de carga, latência real Render–Neon, failover ou pooler.
- Cluster mantido ligado durante os probes coordenados e encerrado ao finalizar a auditoria; ver evidência de encerramento nesta pasta.
- Encerrar: `/tmp/compac-pg/root/usr/lib/postgresql/17/bin/pg_ctl -D /tmp/compac-pg/data stop -m fast`.
