# Importação e exportação de documentos — COMPAC

Acesse **Importar e exportar** no menu, ou `/documentos` após entrar no sistema.

## O que está disponível

| Informações | Importar | Exportar |
| --- | --- | --- |
| Materiais | CSV e Excel XLSX, usando o modelo | PDF, Excel XLSX, CSV e Word DOCX |
| Estoque inicial | Planilha de materiais; quantidade positiva gera uma entrada rastreável | No relatório de estoque e no histórico |
| Movimentações | CSV e XLSX com códigos, localizações e finalidade | PDF, XLSX, CSV e DOCX |
| Estoque atual | Recebimentos e demais movimentações; não substituir um saldo pronto | PDF, XLSX, CSV e DOCX |
| Empréstimos pendentes | Abertura/devolução por movimentação válida | PDF, XLSX, CSV e DOCX |
| Dashboard | Não: é um resumo calculado dos registros | PDF, XLSX, CSV e DOCX |
| Senhas, sessões, tokens e biometria | Não | Não |

PDF e Word são relatórios de leitura; não há OCR ou interpretação automática de notas, fotografias ou documentos livres. Editar um relatório fora do sistema não altera os registros. Arquivos antigos `.xls`/`.doc`, arquivos com macros e planilhas com fórmulas/links não são aceitos como importação.

## Importar com conferência

1. Escolha **Materiais e estoque inicial** ou **Movimentações**.
2. Baixe o modelo Excel ou CSV. Use os cabeçalhos do modelo, sem renomeá-los.
3. Preencha até 500 linhas, em arquivo de até 2 MB. Quantidades usam vírgula ou ponto decimal, no máximo três casas, sem separador de milhar. Quantidade negativa é recusada; estoque inicial zero é permitido.
4. Clique em **Analisar planilha** e confira as linhas, erros e avisos. Essa prévia não salva materiais, movimentos ou saldos.
5. Corrija erros e gere outra prévia, se necessário. Só confirme quando os dados estiverem corretos. A prévia vale 15 minutos e pertence à conta que a criou.
6. Clique em **Confirmar importação**. O lote inteiro é gravado em uma transação; falha em uma linha cancela todas. A confirmação gera identificador de lote, auditoria e movimentos rastreáveis.

Não reenvie um lote como nova importação sem verificar seu resultado. Repetir a confirmação da mesma prévia não duplica os registros. Depois de perda de conexão, tente a confirmação original; se a prévia tiver expirado, confira o histórico antes de preparar outro lote.

Categorias, locais, códigos de materiais e matrículas devem corresponder aos cadastros existentes. Código de material duplicado é recusado; a importação não mescla descrições semelhantes nem edita o saldo de materiais existentes.

### Modelo de materiais

Cabeçalhos: `codigo`, `descricao`, `categoria`, `unidade`, `minimo`, `saldo_inicial`, `local`, `tipo_origem`, `referencia`.

`saldo_inicial` pode ficar vazio ou ser zero. Para quantidade positiva, informe o local e o tipo de origem: `INVENTARIO_INICIAL`, `NOTA_FISCAL` ou `OUTRO_RECEBIMENTO`. Nota fiscal/outro recebimento exigem referência identificadora. Não há lançamento fiscal/financeiro automático.

### Modelo de movimentações

Cabeçalhos: `tipo`, `codigo_material`, `quantidade`, `origem`, `destino`, `matricula`, `finalidade`, `tipo_origem`, `referencia`, `observacoes`.

- `ENTRADA`: destino, quantidade e origem documental válidos.
- `SAIDA`: origem e finalidade `CONSUMO` ou `EMPRESTIMO`. Consumo pode identificar responsável sem gerar pendência; empréstimo exige matrícula.
- `TRANSFERENCIA`: origem e destino distintos.
- `DEVOLUCAO`: matrícula, material, destino e quantidade compatíveis com pendências existentes. Na instalação COMPAC, a baixa segue a ordem das retiradas daquele funcionário/material; a prévia apresenta esse aviso.

Ajustes não são importados em lote: devem ser feitos pelo administrador, com justificativa. Datas do arquivo não substituem o horário do servidor.

## Exportar e compartilhar

Selecione informações, formato e filtros. A prévia mostra até 50 linhas; o arquivo inclui todos os registros filtrados, dentro do limite do formato. Arquivo vazio contém cabeçalho, sem dados fictícios. Datas incluem o dia final completo no fuso da operação.

**Disponível** é o saldo físico nos locais selecionados. **Emprestado** é o que ainda precisa ser devolvido, atribuído ao local da retirada. **Total sob controle** é a soma dos dois, separada por unidade. Períodos filtram os fluxos; o estoque continua sendo a posição atual, não uma posição reconstruída no passado.

| Formato | Limite por arquivo | Uso |
| --- | --- | --- |
| PDF | 2.000 linhas | Leitura/impressão, cabeçalhos repetidos por página |
| Word DOCX | 3.000 linhas | Documento editável fora do sistema |
| Excel XLSX | 10.000 linhas | Planilha, preservando os decimais exportados |
| CSV | 50.000 linhas | Intercâmbio de dados; UTF-8 com BOM e separador `;` |

Acima do limite, refine filtros e exporte novamente; não há corte silencioso de registros. Planilhas exportadas neutralizam conteúdo que poderia ser interpretado como fórmula.

**Compartilhar arquivo** abre o compartilhamento do dispositivo quando ele aceita arquivos, permitindo escolher um aplicativo disponível. Nos demais navegadores, o documento é baixado para anexar manualmente. Nenhuma mensagem é enviada automaticamente e não existe integração automática com contas de WhatsApp.

Consulta pode exportar as informações operacionais que já tem autorização para ver. Importação e gravações exigem Operador/Administrador e sessão válida no momento da confirmação. Não existe exportação geral do banco por essa central.
