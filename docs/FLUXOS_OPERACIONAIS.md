# Auditoria operacional — Compac

Escopo: ETAPA ZERO do documento completo mais recente; leitura do código e probes sobre SQLite e PostgreSQL locais descartáveis, sem mudança em código de aplicação, banco real, Render ou Neon. Base: commit `6a24fa7`. As propostas seguintes são desenho de evolução, não funcionalidades entregues.

## Estrutura e invariantes existentes

- `materials` é cadastro sem saldo, com código único, descrição, unidade, categoria e mínimo global (`app/catalog.py:17–23`, `app/db.py:20`). A API rejeita campos extras no catálogo (`app/main.py:315–318`); portanto a edição normal não consegue gravar `quantity` em materiais.
- `balances` é a projeção de saldo por `(material_id, location_id)`, em milésimos inteiros e com `CHECK(quantity>=0)` (`app/db.py:22`). Não há rota pública para editar a tabela diretamente.
- `movements` guarda entrada/saída/transferência/devolução/ajuste, usuário, instante UTC, origem e destino físicos, funcionário opcional, justificativa e vínculo opcional de requisição (`app/db.py:25`, `app/main.py:397–447`). `origin_id` significa localização de origem; não representa fornecedor, NF ou tipo de recebimento.
- `loans` guarda a pendência restante de cada saída com funcionário (`app/db.py:26`); saída com funcionário diminui saldo e abre empréstimo; saída sem funcionário é consumo/saída definitiva. Devolução parcial reduz pendências FIFO do funcionário/material e aumenta saldo no destino escolhido (`app/main.py:421–446`).
- Todos esses caminhos de gravação usam `connect(write=True)`: SQLite usa `BEGIN IMMEDIATE`; PostgreSQL usa advisory lock transacional global, `lock_timeout=15s`, `statement_timeout=20s`; exceções fazem rollback (`app/db.py:132–165`). Isso preserva o padrão atual de escritor serializado, mas limita o paralelismo.
- Ajustes só por administrador, com justificativa obrigatória; a entrada informada é saldo final, mas o movimento gravado contém a diferença, inclusive negativa (`app/main.py:401–414`, `438–447`). Essa semântica precisa ser preservada em qualquer migração/reconciliação.
- Cadastro e alterações têm auditoria, e a movimentação registra auditoria na mesma transação. Histórico é consultável, sem rota HTTP de apagar movimento.

## Matriz de funcionalidades verificadas

| Fluxo | Existente | Lacuna verificada |
|---|---|---|
| Material | CRUD sem exclusão, código único ignorando caixa, categoria/unidade/status | Sem quantidade inicial, local/origem no cadastro; sem ação específica de adicionar estoque na lista de materiais |
| Estoque | Saldo por local, entrada/saída/transferência/ajuste rastreáveis | API/tela de estoque não somam empréstimos nem mostram total sob controle; mínimo só global |
| Recebimento | ENTRADA individual em movimentações | Sem documento de recebimento, itens de NF, vínculo de fornecedor/NF/custo/data recebimento com entrada, origem estruturada ou idempotência |
| Empréstimo | Saída com funcionário, prazo opcional, pendência, devolução parcial/FIFO, alerta de atraso | Sem transferência formal de custódia, avaria/perda/comprovante consolidado; sem vínculo explícito devolução→empréstimo; unidade patrimonial não acompanha o empréstimo |
| Requisição | Cabeçalho+itens (1–100), aprovação ADMIN, cancelamento, atendimento integral por transferências, checagem de obra destino e guarda de estado | Leitura N+1; criação sem idempotência; não reserva saldo nem permite atendimento parcial |
| Patrimônio/manutenção | Etiqueta única, material individualizável, localização/condição/status; abertura única de manutenção e conclusão | Cadastro de unidades patrimoniais e status/local de equipamento não se reconciliam com `balances`; não existe vínculo `equipment_id` em saída/loan para rastrear qual ferramenta foi entregue |
| Gastos | Fornecedor texto, documento, data compra, material/obra, quantidade/custo/total; auditoria | Cadastro de gasto não recebe estoque; ausência de cabeçalho NF e documento multitem e ausência de cadastro de fornecedor |
| Previsão | Coeficientes por obra/atividade, produção, soma e faltante vs saldo da obra | Não é sugestão de compra formal; não mede consumo real vinculado à produção |
| Alertas | Abaixo de mínimo global; empréstimo vencido; chamado urgente | Sem mínimo por localização/obra; sem alertas EPI/CA |
| Relatórios | CSV de estoque, movimentos, gastos, requisições, chamados, produção; auditoria limitada a últimos 2000 | Sem Excel nativo, PDF, comprovante consolidado, relatório mensal presença, QR patrimonial |
| Presença / EPI / inventário | Ajuste manual de saldo com justificativa e permissão | Não há entidades nem fluxos de presença, CA/validade/EPI, inventário físico com contagens, aprovação e divergências |

## Achados confirmados e evidência

### OP-01 — ALTO: repetição duplica entradas e demais movimentos

`app/main.py:451–454` chama `perform_movement` para todo POST; schema não possui chave de idempotência nem unicidade de requisição (`app/db.py:25`). Prova: dois POSTs iguais de ENTRADA de 2 UN, ambos com `Idempotency-Key: audit-same-request`, retornaram 201 com IDs 1 e 2 e saldo 4. O header é ignorado. Serialização de escritas impede corrida de saldo negativo, mas não identifica a mesma operação de negócio enviada novamente. O mesmo risco existe em saídas/devoluções parciais enquanto houver saldo/pendência suficiente. Não há necessidade de concorrência para reproduzir.

Prioridade: antes de ativar recebimentos em lote ou usar rede móvel. Usar chave de operação persistente+hash do conteúdo e resultado, na mesma transação do movimento. Desabilitar botão é complementar.

### OP-02 — ALTO: mudança de unidade reinterpreta saldos e histórico

`app/main.py:369–380` permite editar `materials.unit` mesmo com saldo/movimentos/empréstimos; listagens e CSV juntam `materials.unit` atual (`app/main.py:460`, `464`, `476`, `692`). Prova: após duas entradas de 2 UN, editar para KG retornou 200; saldo passou a aparecer como 4 KG e os dois movimentos anteriores também como KG, sem conversão nem nova movimentação. Não é alteração direta de `balances.quantity`, mas muda o significado físico do saldo.

Prioridade: bloquear alteração da unidade/individualização quando houver histórico relevante, ou criar processo explícito de conversão com rastreabilidade. Capturar unidade no novo documento e garantir semântica dos históricos antigos. A auditoria cadastral contém antes/depois, porém os relatórios usuais não os utilizam para reconstruir unidade histórica.

### OP-03 — MÉDIO: modelo patrimonial independente do controle quantitativo

`equipment` referencia material/local, mas nenhum movimento ou empréstimo referencia a unidade patrimonial; CRUD pode alterar local/status do equipamento sem passar por transferência de saldo (`app/main.py:345–347`, `376–379`; `app/db.py:21`, `25–26`). A manutenção muda status do equipamento, mas não bloqueia quantitativo do material (`app/main.py:612–637`). É lacuna confirmada do modelo; não concluir que houve perda real ou que um dado de produção está incorreto. Impede garantir qual patrimônio foi entregue e se o saldo disponível exclui itens em manutenção.

Prioridade: definir regras de conciliação e vínculo de patrimônio às entregas antes de prometer rastreamento individual/QR; migração não deve fabricar correspondências de unidades para movimentos antigos.

### OP-04 — MÉDIO: total de estoque não inclui custódia externa e termos são ambíguos

`stock_rows` só lê balances e material (`app/main.py:463–470`); loans são endpoint separado (`473–476`). A tela chama o saldo de disponível e soma só as localizações (`app/static/app.js:779–817`). Prova: após disponível 4, empréstimo 1 e devolução 0,25, endpoint estoque informa 3,25 e loans 0,75; nenhum retorno informa total 4 sob controle.

Definição proposta: saldo em estoque = soma balances; emprestado = soma loans.quantity positiva; total quantitativo sob controle = ambos. Retiradas definitivas, perdas/baixas futuras e consumos não integram total. Requisições atuais não reservam estoque. Para patrimônio, chamar esse primeiro número de saldo contábil até existir reconciliação de manutenção/bloqueios; não prometer disponibilidade física individual que o modelo não representa.

### OP-05 — MÉDIO: recebimento e gasto não têm transação compartilhada

`expenses` é cadastro genérico que calcula total, mas não gera movimento (`app/main.py:343–365`). Prova: cadastrar gasto de 3 unidades a R$25 com NF fictícia manteve saldo4 e contagem de movimentos2. Isso é funcionalidade incompleta para o novo pedido, não corrupção do fluxo atual. Não preencher retroativamente saldo a partir de expenses: compras históricas podem já ter ENTRADA manual, duplicando estoque.

### OP-06 — MÉDIO: ausência de migrações versionadas e teste de restauração

Inicialização usa CREATE TABLE/INDEX IF NOT EXISTS (`app/db.py:167–176`); não há versão/checksum de schema ou execução controlada de ALTER. Suite existente não tem testes de migração/restauração; testes PG são condicionais à variável de banco de teste (`tests/conftest.py:15–44`). Presença de driver e conversão do DDL não demonstra compatibilidade de todas as evoluções. Probes operacionais foram repetidos em PostgreSQL local descartável; não executado PG remoto nem produção.

### OP-07 — BAIXO: deduplicação de material é por código

Código duplicado ignorando caixa retorna409 (verificado nos dois motores), mas descrições equivalentes com códigos diferentes são permitidas. Isso é regra incompleta a definir, não necessariamente bug: materiais podem legitimamente compartilhar descrição. SQLite NOCASE e PostgreSQL LOWER não têm normalização Unicode idêntica; se códigos não ASCII forem permitidos, a equivalência entre motores precisa ser testada/definida. Não mesclar cadastros automaticamente em migração.

Risco financeiro a validar: `validate_entity` converte valores para float, calcula Decimal a partir desses floats e volta a float (`app/main.py:327`, `343–344`); SQLite usa REAL para gastos e `Record` também transforma NUMERIC/Decimal PG em float (`app/db.py:29`, `67–71`). Isso merece limites, política de arredondamento e testes monetários de grandes valores; este relatório não afirma uma perda monetária específica sem reprodução.

## Evidências de teste específicas

Comando SQLite: `.venv/bin/python scripts/audit_operations.py` com rede habilitada para TestClient local. O script remove DATABASE_URL e configura SQLite em TemporaryDirectory. Resultado JSON: `docs/evidencias/operacoes-sqlite.json`.

Comando PostgreSQL: `COMPAC_OPERATION_AUDIT_PG_URL='postgresql://compac_audit@127.0.0.1:55439/compac_audit' .venv/bin/python scripts/audit_operations.py`. Servidor e banco exclusivamente de auditoria; script cria schema `operations_<uuid>`, usa search_path isolado e remove apenas esse schema no finally. Resultado `docs/evidencias/operacoes-postgresql.json`: idêntico ao SQLite para todas as verificações abaixo, inclusive duplicação, unidade histórica e rollback da falha de auditoria. Nenhuma credencial real ou dado real foi usado.

| Verificação | Resultado |
|---|---|
| Criar material sem movimento | Saldo0, localização nula; cadastro preservado |
| Enviar initial_quantity/location no cadastro | 422 por campos desconhecidos |
| Código duplicado alterando caixa | 409 |
| Repetir ENTRADA com mesma chave | Dois201, IDs diferentes, saldo duplicado (OP-01) |
| ENTRADA negativa/zero | 422/422 (inicial zero é requisito novo; AJUSTE zero já existe) |
| PUT material com campo quantity | 422; não altera saldo |
| PUT unidade após movimentos | 200 e histórico reetiquetado (OP-02) |
| Registrar despesa com NF | 201; saldo e movimento inalterados |
| Empréstimo1 + devolução0,25 | Saldo3,25; pendência0,75 |
| Falha injetada em audit após INSERT movimento | 500; saldo, movimentos, loans e quantidade de registros de auditoria idênticos ao antes; rollback funciona |

Cobertura já existente (root executa a suíte): `tests/test_workflows.py:125` precisão e rollback de insuficiência; `138` duas retiradas concorrentes sem overspend; `160` devolução parcial/excesso/inativos; `177` conservação na transferência e ajuste zero; `224` rollback integral no atendimento multitem e obra correta; `274` manutenção; `296` perfis; `tests/test_database.py:43` grandes quantidades/persistência. Lacunas: idempotência, cadastro+entrada atômicos, NF multitem, falha entre itens de recebimento, migrações, backup/restauração, concorrência recebimento, reconciliação patrimonial e regressão de unidade.

## Plano aditivo de migração e implementação posterior

1. **Baseline e critérios.** Criar `schema_migrations(version, checksum, applied_at)` e arquivos SQL/revisões explícitas para SQLite e PostgreSQL. Testar migração de fixture da versão atual. Validar contagens de materials/balances/movements/loans, somas por material/local e referências; gerar backup em ambiente autorizado e ensaiar restauração em banco descartável. Guardar baseline de histórico; não recalcular saldos de gastos, não apagar/reescrever movimentos, não inventar origem de registros legados.
2. **Aditivas para documentos.** Introduzir fornecedor (identificador estável), cabeçalho de documento/operação (`kind` INVENTARIO_INICIAL/NOTA_FISCAL/OUTRO, fornecedor opcional, documento/identificador de origem, data recebimento, usuário e instante criação) e itens (`material_id`, localização destino, quantidade em milésimos, custo unitário decimal, vínculo opcional único de movement_id). Manter movements/balances como trilha e projeção atuais; a tabela de itens pode referenciar movimentos existentes sem ALTER destrutivo. Registros históricos ficam sem documento novo e são exibidos como legado/origem não informada.
3. **Identificação de NF e reenvio.** Idempotência persistente por usuário/escopo/chave com hash canônico do payload e resposta final. Mesma chave+payload retorna a operação original; mesma chave+payload diferente devolve409. Chave empresarial de recebimento/NF tem regra separada (fornecedor, número e série/chave identificada); definir dados fiscais necessários antes de proibir números iguais entre fornecedores. Chave e todos os efeitos devem confirmar na mesma transação. Manter bloqueio global atual até medir alternativa segura.
4. **Serviço transacional único.** Cadastro de material aceita seção inicial separada, somente no POST. Valida material/local/origem/custo/permissão; cria cadastro, documento/item, movimento ENTRADA se quantidade>0, saldo e auditoria sob um `connect(write=True)`. Com quantidade0, criar material e registrar metadados iniciais+auditoria sem inventar ENTRADA de quantidade positiva; movimento opcional do item nulo documenta essa regra. Quantidade negativa rejeitada. PUT de cadastro continua estrito sem saldo e passa a proteger unidade com histórico. Existing materials recebem ação Adicionar estoque, chamando o mesmo serviço de recebimento.
5. **Recebimento multitem.** Cabeçalho único de NF, lista limitada de itens; validar todos antes dos efeitos; cada item produz ENTRADA vinculada. Falha em qualquer item ou auditoria reverte todos. Agrupar/rejeitar linhas repetidas conforme material/local; fornecer total em Decimal sem propagação financeira por float. O cálculo de gastos precisa de regra explícita e vínculo único para não duplicar expenses antigos nem gerar custo duas vezes em reenvio.
6. **Leitura e interface.** Exibir saldo em estoque, emprestado e total sob controle por material e por localização de origem dos empréstimos; explicar que requisição não reserva. Índices e agregações em consultas paginadas, evitando fanout de JOIN entre vários balances e loans que multiplicaria somas. Filtro por documento, fornecedor, data/local, autor. Formulário inicial não aparece na edição; botão Adicionar estoque separado. Conservar identidade visual.
7. **Gates.** Testar em SQLite e PostgreSQL descartáveis: zero/negativo; estoque inicial; rollback após material/primeiro item/movimento/auditoria; reenvio sequencial e concorrente; mudança de payload; duplicação por código/NF; dois itens e localizações; empréstimos/devoluções parciais; mesma quantidade total antes/depois da migração; unidade imutável; políticas OPERADOR/CONSULTA/ADMIN; cancelamento/reversão futura por contramovimento. Só então preparar piloto e autorização específica de produção. Rollback inicial por desativação da feature/versão do código, mantendo tabelas aditivas e dados; não apagar tabelas que já receberam dados.

Nenhuma correção ou migração foi aplicada na aplicação. PG/Neon real permanece fora do escopo executado.
