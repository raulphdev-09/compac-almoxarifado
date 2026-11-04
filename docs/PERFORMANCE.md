# COMPAC — linha de base de performance

Data: 04/11/2026. Base `6a24fa7`. **Antes de otimizar**; nenhum resultado “depois” é declarado nesta etapa. Dados exclusivamente fictícios e infraestrutura local, sem tráfego ou banco de produção.

## Método SQLite/API

Comando: `.venv/bin/python scripts/audit_baseline.py --output artifacts/audit-baseline.json`. Evidência preservada: [baseline-sqlite.json](evidencias/baseline-sqlite.json).

Python 3.12.14, SQLite 3.53.1. Cada cenário cria SQLite em TemporaryDirectory, remove variáveis de produção do processo e descarta o banco ao final. Em N movimentos existem N/10 materiais e N/10 requisições de um item, uma localização e obra; sem empréstimos, despesas ou chamados. As entradas e os saldos gerados são coerentes. Duas leituras de aquecimento, 30 amostras sequenciais por endpoint. Inclui TestClient, middleware, autenticação, consultas, conversão e serialização. Não mede só o tempo interno do servidor, rede pública, concorrência ou cold start.

p50 é mediana; p95/p99 são nearest-rank. Com 30 amostras, p99 equivale ao máximo observado e é apenas exploratório. Medições ocorreram em ambiente compartilhado com outras auditorias; não são certificação de capacidade.

| Endpoint | Movimentos | p50 ms | p95 ms | p99 ms | JSON bytes | SQLs |
|---|---:|---:|---:|---:|---:|---:|
| GET movements | 100 | 5,021 | 5,705 | 6,204 | 37.603 | 2 |
| GET movements | 1.000 | 27,377 | 29,115 | 45,932 | 377.814 | 2 |
| GET movements | 10.000 | 239,901 | 317,080 | 349,603 | 3.797.825 | 2 |
| GET requisitions | 100 | 2,876 | 3,219 | 3,317 | 3.235 | 12 |
| GET requisitions | 1.000 | 5,935 | 7,673 | 9,507 | 32.669 | 102 |
| GET requisitions | 10.000 | 53,278 | 74,626 | 89,009 | 330.573 | 1.002 |
| GET stock | 100 | 2,632 | 3,228 | 3,235 | 1.822 | 2 |
| GET stock | 1.000 | 5,232 | 7,806 | 7,984 | 18.293 | 2 |
| GET stock | 10.000 | 15,425 | 18,490 | 18,661 | 183.894 | 2 |
| GET dashboard | 100 | 3,267 | 3,550 | 3,596 | 1.160 | 11 |
| GET dashboard | 1.000 | 3,354 | 8,611 | 11,839 | 1.168 | 11 |
| GET dashboard | 10.000 | 2,763 | 3,050 | 3,099 | 1.176 | 11 |
| GET catalog/materials | 100 | 3,025 | 3,305 | 3,769 | 1.572 | 2 |
| GET catalog/materials | 1.000 | 3,918 | 7,258 | 7,693 | 15.793 | 2 |
| GET catalog/materials | 10.000 | 14,040 | 15,596 | 30,324 | 158.894 | 2 |
| POST movements | 100 | 2,859 | 3,410 | 3,710 | — | — |
| POST movements | 1.000 | 2,576 | 2,998 | 3,008 | — | — |
| POST movements | 10.000 | 2,425 | 2,674 | 2,817 | — | — |

As gravações ocorrem depois das leituras de cada cenário e adicionam 30 entradas positivas descartáveis. SQLs foram contados em requisição separada, por instrumentação de Database.execute, incluindo autenticação. O arquivo JSON guarda índices e o plano SQLite: busca de itens por requisição faz `SCAN requisition_items`.

## PostgreSQL: separar consulta de API

Relatório completo: [VALIDACAO_POSTGRESQL.md](VALIDACAO_POSTGRESQL.md); [planos JSON](evidencias/postgresql/). PostgreSQL 17.11 local, TCP loopback, 50 materiais, N movimentos, N loans (metade abertos), N/10 requisições de **dez itens** e N/10 despesas. Essa fixture é de volume SQL, não uma simulação coerente de custódia física. Portanto seus números de API não são uma comparação controlada de velocidade entre SQLite e PostgreSQL.

Com 10 mil movimentos, a consulta SQL completa de movimentos executou em **14,993 ms** no EXPLAIN aquecido, mas a API levou **p95 450,937 ms**, devolvendo **3.205.295 bytes**. Isso mostra o custo fora do plano SQL: conexão, objetos, middleware, serialização e cliente. Não atribuir toda a latência ao banco.

Com 1.000 requisições/10 mil itens, a API fez **1.002 SQLs**, devolveu **1.289.118 bytes** e teve **p50 649,361 / p95 707,301 / p99 720,669 ms**. 20 amostras sequenciais após aquecimento; caudas indicativas. Uma consulta de itens retornou 10 linhas e descartou 9.990 por Seq Scan. Sem índice de requisition_id, o N+1 multiplica a varredura e, em banco remoto, os round trips.

Seq Scan em pequenas dimensões e em listagem completa não é defeito isoladamente. Prioridade: remover N+1 e limitar resposta; depois medir índices específicos para requisição/material/local/pendência/data, com distribuição realista. Não criar índices em todas as colunas sem EXPLAIN e avaliação do custo de escrita.

## Navegador

Probe real de renderer com catálogo interceptado de materiais fictícios, Chromium local 1440 px. Uma amostra por volume, sem limitação de CPU. Mede do refresh até linhas renderizadas e duas animation frames; filtro inclui handler síncrono e layout forçado. Não é p95 nem tempo de API.

| Materiais/linhas | Renderização | Filtro síncrono |
|---:|---:|---:|
| 100 | 103 ms | 6,4 ms |
| 1.000 | 432 ms | 47,5 ms |
| 10.000 | 3.489 ms | 475,7 ms |

Fonte: [probe-results.json](evidencias/interface/probe-results.json), [INTERFACE_PWA.md](INTERFACE_PWA.md). Tabela inteira e filtros de cada input operam sobre todo o DOM. Paginação no servidor e na UI é prioritária; debounce isolado não elimina o custo de carregar/renderizar tudo.

## Gargalos, transações e conexões

- Listas completas em materiais/movimentos/requisições/chamados/manutenção; auditoria tem corte fixo de 2.000 e não pagina registros antigos; exports carregam resultados em memória antes de produzir CSV.
- N+1 em requisitions, além de validações individuais de relações. Dashboard faz 11 SQLs incluindo autenticação; alerts também é chamado separadamente na UI. Consolidar somente depois de medir e preservar semântica.
- Conexões PostgreSQL são abertas por contexto; não há pool Python. `prepare_threshold=None` favorece compatibilidade com pooling de transações, mas não comprova a saúde/configuração do pooler remoto. Não mudar driver/pool sem medir o ambiente alvo.
- Lock global serializa inclusive login e outras escritas que usam `connect(write=True)`. É proteção de consistência confirmada e potencial gargalo, não autorização para removê-la. Medir wait/hold times sob carga e planejar locks ordenados/updates condicionais somente se justificado.
- A PWA não guarda dados operacionais offline; não introduzir cache de respostas privadas para esconder latência sem projeto de invalidação/segurança.

## Metas e próxima medição

As metas do pedido (API comum p95<300 ms, pesquisa paginada<500 ms, operação de estoque<800 ms) referem-se ao servidor aquecido. O baseline local de percurso completo indica gargalos, mas não prova aprovação/reprovação do SLA de produção. Ainda não existe pesquisa paginada para medir seu contrato final. Não há teste de saturação nem de rede/cold start real da hospedagem gratuita.

Após as correções, repetir os mesmos scripts e fixtures, acrescentar amostras suficientes para caudas, concorrência e distribuição realista. Separar tempos de middleware/SQL/lock, rede, render e cold start. Registrar taxa de erros e tamanho da resposta; não otimizar apenas a mediana. Manter resultados antes e depois e aprovar metas em homologação representativa.

Nenhuma otimização de produção foi aplicada nesta etapa.
