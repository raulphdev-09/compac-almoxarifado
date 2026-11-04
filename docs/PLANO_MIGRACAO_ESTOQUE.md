# Plano aditivo — estoque inicial e recebimento de materiais

Status: **proposta para implementação posterior à auditoria**, sem migração executada e sem mudança em produção. A referência é o código `6a24fa7`, com os achados de [auditoria](AUDITORIA_TECNICA.md) e os [fluxos existentes](FLUXOS_OPERACIONAIS.md).

## 1. Regras que precisam permanecer verdadeiras

1. `materials` continua sendo cadastro. Quantidade não será um campo editável de saldo no PUT cadastral.
2. `movements` continua sendo a trilha de entradas, saídas, devoluções, transferências e ajustes; `balances` é sua projeção por material/local.
3. Empréstimos ativos ficam em `loans`. Devoluções parciais, consumo sem funcionário, histórico de requisições e ajuste por **delta** precisam manter a semântica atual.
4. Material/documento/itens/movimentos/saldos/custos vinculados/auditoria/idempotência confirmam numa única transação. Uma falha reverte todos.
5. Quantidade em milésimos inteiros. Negativos são recusados no recebimento; zero é permitido no cadastro inicial. Não impor CHECK global de movimento positivo: ajustes históricos podem ter delta negativo.
6. Serialização atual das escritas permanece até uma alternativa passar em testes e medições de contenção.

## 2. Matriz dos 16 requisitos

| Requisito | Estado atual | Mudança planejada |
|---|---|---|
| 1. Quantidade inicial | Ausente no formulário/API | Seção inicial somente no POST de material |
| 2. Localização | Existe no movimento separado | Seleção de localização no cadastro inicial/recebimento |
| 3. Origem identificada | Só notas livres; origin_id é local físico | Tipo INVENTARIO_INICIAL/NOTA_FISCAL/OUTRO e identificador obrigatório conforme tipo |
| 4. Criar material e entrada juntos | Hoje são duas operações | Serviço transacional único |
| 5. Atualizar saldo local | Já existe em perform_movement | Reutilizar a regra interna de projeção, sem escrita isolada |
| 6. Movimento e auditoria | Já atômicos para movimento separado | Incluir documento e vínculo cadastral na mesma transação |
| 7. Negativo proibido | Movimento negativo já recusado | Manter validação e constraints nos novos itens |
| 8. Zero permitido | Material já nasce sem saldo; ENTRADA zero é recusada | Cadastro inicial com zero, metadados/auditoria; sem criar uma entrada positiva fictícia |
| 9. Adicionar estoque | Movimento genérico separado | Ação explícita no material existente, usando serviço de recebimento |
| 10. Edição sem saldo | Campo estranho já é recusado | Preservar whitelist, proteger unidade/individualização com histórico |
| 11. Material duplicado | Código único sem distinguir caixa | Preservar unicidade no banco, definir normalização e aviso de possíveis equivalentes |
| 12. Reenvio duplicado | Bug confirmado | Chave persistente + hash de payload + resposta na mesma transação |
| 13. NF com vários itens | Ausente | Cabeçalho e itens limitados, confirmação integral |
| 14. Fornecedor/NF/data/custo | Há em despesas individuais, desvinculadas | Vincular ao recebimento, sem inferir entradas de gastos antigos |
| 15. Disponível/emprestado/total | Só disponível no estoque; loans separado | Métricas e definições lado a lado, agregações sem fanout |
| 16. Preservar histórico | Nenhuma migração versionada | Baseline, backup/restore, migrações aditivas e comparações antes/depois |

## 3. Esquema proposto e versão

Criar revisões explícitas por banco, com `schema_migrations(version, checksum, applied_at)`. Runner deve reconhecer o schema atual, recusar revisões divergentes, serializar aplicação e registrar sucesso na mesma transação quando suportado. No SQLite, não presumir que o atual executescript preserva uma transação externa: ele pode confirmar implicitamente antes do script; o runner precisa controlar BEGIN/COMMIT/ROLLBACK e testar falhas entre instruções. Testar reaplicação, interrupção e schema legado antes de disponibilizar a revisão. A primeira baseline registra a estrutura existente sem apagar/recriar tabelas. Não ativar migração de produção automaticamente por simples inicialização do novo código.

Novas tabelas propostas, com nomes finais sujeitos à implementação:

- `suppliers`: identidade estável do fornecedor, nome e identificador comercial quando necessário; restrições e minimização de dados definidas no contrato.
- `stock_documents`: tipo da origem, fornecedor opcional, número/série/chave de NF quando aplicável, identificador de outros recebimentos, data operacional de recebimento, usuário criador e instante UTC.
- `stock_document_items`: documento, material, localização destino, quantidade_milli, unidade congelada na operação, custo unitário e vínculo opcional **único** com um movimento. Quantidade não negativa; zero só para item de inventário inicial. Recebimento efetivo exige quantidade positiva.
- `operation_requests`: ator/escopo/chave única, hash canônico do conteúdo e resposta/status da operação concluída. O registro e os efeitos de negócio confirmam juntos.

Custos devem ter representação exata nos dois motores: por exemplo, custo unitário em centavos inteiros e totais calculados com Decimal, caso o contrato adote duas casas. Se preços exigirem mais casas, definir escala explicitamente antes de codificar. Limitar totais/itens para evitar overflow. Não converter custos novos por float, nem alterar automaticamente valores históricos de `expenses`.

Índices candidatos: itens por documento/material; documentos por fornecedor/número/data; vínculo único do movimento; unicidade de idempotência; `requisition_items(requisition_id)` e filtros de pendências conforme planos medidos. Unicidade fiscal e idempotência HTTP são proteções diferentes. Definir identificação da nota por fornecedor+número+série ou chave fiscal; número sozinho não é globalmente único.

Os históricos antigos permanecem sem vínculo de documento novo e devem ser apresentados como “legado / origem não informada”. Não inferir NF/fornecedor de texto livre nem criar entrada a partir de expense: a compra pode já ter entrada manual.

## 4. Contratos e transação

Novo material: POST aceita metadados cadastrais e uma seção `initial_stock` distinta. O PUT continua estrito e recusa essa seção. Para quantidade maior que zero, exigir local e origem válida; no zero inicial, permitir informar local/origem para documentar a contagem sem exigir uma localização artificial quando ainda desconhecida. Essa regra deve aparecer explicitamente no formulário e no contrato.

Recebimento: operação com cabeçalho e lista limitada de itens, todos validados no backend (quantidade, fornecedor, data, custo, material/local ativo, duplicidade de linha e documento). Formulário e API compartilham a mesma política, mas o backend é a autoridade.

Sequência dentro de um `connect(write=True)`:

1. Verificar permissão e obter/validar a chave de operação. Normalizar o conteúdo antes do hash, incluindo quantidades decimais e identificadores.
2. Mesma chave e mesmo conteúdo: devolver a operação original, sem novos efeitos. Chave reaproveitada com conteúdo diferente: 409. Não gravar resposta incompleta como sucesso.
3. Criar material quando aplicável; unicidade de código continua garantida no banco e conflito reverte tudo.
4. Criar documento/itens. Para cada quantidade positiva, aplicar ENTRADA pela regra interna existente, vinculando movimento/documento e atualizando saldo local. Inicial zero gera documento/item/auditoria sem movement_id, mantendo a regra atual de ENTRADA positiva; o histórico de estoque deve também listar esse documento como “contagem inicial zero”, sem efeito no saldo.
5. Registrar origem, usuário, instante, data de recebimento e locais. Se houver integração de gastos, criar o lançamento vinculado uma única vez, conforme regra contábil aprovada.
6. Confirmar auditoria e resultado idempotente juntamente com todos os efeitos. Qualquer exceção aborta toda a operação.

Client gera uma chave por intenção de operação e mantém a mesma chave em retries. Botão desabilitado ajuda a UX, mas não substitui unicidade transacional. Uma NF repetida com outra chave também precisa de regra de deduplicação de documento. Não usar um intervalo de tempo para presumir duplicidade: duas entregas reais iguais podem ser legítimas.

Permissões propostas: ADMIN e OPERADOR recebem material/adicionam estoque; CONSULTA só lê; ajuste/contagem autorizada continua ADMIN. Definir quem pode ver custos e documentos se a empresa quiser um escopo mais restrito que o atual. Não ampliar silenciosamente acesso financeiro.

INVENTARIO_INICIAL fica reservado ao cadastro de material novo, sem histórico. Para material existente, Adicionar estoque representa recebimento real identificado (nota ou outra entrada); divergência de contagem posterior segue o fluxo AJUSTE de ADMIN com justificativa. Validar essa distinção no backend para que a escolha de origem não se torne um caminho alternativo à autorização de ajustes.

## 5. Leitura de estoque e interface

- **Saldo em estoque:** soma dos balances nas localizações selecionadas; é saldo quantitativo contábil.
- **Emprestado:** soma positiva das pendências de loans, atribuída ao material e à localização de origem/custódia definida.
- **Total quantitativo sob controle:** saldo em estoque + emprestado. Saída definitiva/consumo não integra esse total. Requisição atual não reserva saldo.
- **Disponibilidade física de patrimônio:** depende de reconciliar equipamentos em manutenção, baixados, reservados e em uso. Até existir esse vínculo, explicar o limite do saldo contábil e não afirmar que todo patrimônio registrado está fisicamente liberado.

Agregar saldos e empréstimos em subconsultas separadas antes de combinar. JOIN de vários balances com vários loans pode multiplicar somas. Testar múltiplas localizações e empréstimos sobre o mesmo material.

No formulário novo, seção de estoque inicial; na edição, somente dados cadastrais; no material existente, ação separada **Adicionar estoque**. Recebimento/NF tem cabeçalho e itens, revisão de totais e confirmação única. Preservar paleta/layout, rótulos e teclado; usar datas no fuso operacional, sem default UTC indevido.

Unidade com histórico fica bloqueada. Conversão futura exige processo explícito, fator definido, contramovimentos e snapshots. Mudanças antigas de unidade que já possam existir não podem ser reconstruídas por adivinhação: sinalizar para conferência autorizada.

## 6. Preservação, aplicação e reversão

Antes da migração autorizada: backup consistente, restauração em banco independente, exportação de contagens/IDs/somas por material/local e empréstimos, constraints/referências e amostra/hash de movimentos. Registrar divergências encontradas sem corrigi-las automaticamente.

Executar primeiro nas fixtures SQLite e PostgreSQL da versão atual. A migração deve somente adicionar estruturas necessárias, sem reset de sequência, exclusão ou recálculo de saldos. Depois comparar os mesmos indicadores e garantir que movimentos/auditoria anteriores não mudaram.

Disponibilizar por feature flag até revisão e homologação. Reversão inicial: desligar a funcionalidade/voltar código compatível mantendo tabelas e lançamentos novos. Não apagar documentos que já geraram movimentos. Corrigir recebimento confirmado por estorno/contramovimento autorizado, nunca apagando a trilha. Produção exige autorização específica, plano de janela e responsável pela conferência.

## 7. Testes de aceitação antes de liberar

- Material inicial com zero, positivo, negativo, precisão excessiva, local inválido, origem ausente e código duplicado.
- Cadastro+documento+movimento+saldo+auditoria: falha injetada depois de cada etapa sem efeitos parciais.
- Recebimento de vários itens/locais com custo; falha no segundo item e na auditoria reverte o primeiro.
- Mesma chave sequencial e concorrente produz uma operação; conteúdo diferente retorna 409; regra de NF duplicada funciona com outra chave/usuário.
- Dois usuários concorrentes recebendo e retirando: sem saldo negativo, perda de atualização ou empréstimo duplicado.
- Empréstimo, devolução parcial/excesso, transferência, ajuste zero e requisição mantêm os resultados atuais.
- CONSULTA/OPERADOR/ADMIN, unidade com histórico, filtros de data/custo e datas na fronteira de dia.
- Migração preserva dados legados, pode ser reaplicada de forma controlada e recusa checksum divergente; simulado de rollback e restore.
- Métricas em várias localizações sem multiplicar somas; disponível+emprestado=total; patrimônio separado conforme definição.
- Navegador desktop/mobile: criar com estoque, adicionar em existente, NF multitem, retry após falha de rede e reabertura; testes em ambos os bancos sem dados reais.

Os testes atuais são a base de regressão. Cadastro inicial e recebimento ainda não foram implementados; os novos critérios acima ainda não estão aprovados.
