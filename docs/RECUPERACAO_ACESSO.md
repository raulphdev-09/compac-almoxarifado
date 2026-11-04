# COMPAC — credenciais e recuperação de acesso

Este procedimento define a política de acesso da fase de segurança. Nenhum reset de produção, comunicação externa ou criação de canal de recuperação foi executado. Não há recuperação pública por e-mail, token de instalação ou pergunta de segurança.

## Troca com sessão válida

Qualquer usuário autenticado, inclusive CONSULTA, pode trocar a própria senha usando `POST /api/auth/password`, enviando somente `current_password` e `new_password`. A nova senha deve seguir a regra atual de 10 a 128 caracteres e ser diferente da anterior. O hash scrypt existente permanece compatível.

A senha atual é conferida no backend. Falhas são limitadas de forma persistente pelos mesmos contadores de conta/origem usados no login; não se envia a senha para logs ou auditoria. Senha atual incorreta retorna 403 e preserva a sessão para corrigir o formulário. Uma troca válida é atômica, registra `TROCAR_SENHA` sem credenciais e revoga **todas** as sessões daquele usuário, incluindo a atual. A resposta confirma `reauthenticate=true` e apaga o cookie; o usuário precisa entrar novamente.

Não enviar senhas em mensagens, URLs, argumentos de shell, tickets ou capturas de tela. A interface deve usar HTTPS e o formulário autenticado. Quem perdeu a sessão segue os procedimentos abaixo.

## Usuário sem acesso, com outro administrador disponível

1. Abrir solicitação no canal interno já reconhecido pela empresa, sem incluir senha ou código de ativação.
2. Um administrador confirma a identidade fora da sessão solicitante, de acordo com o processo da empresa. A simples posse de um e-mail informado ou conhecimento do nome do usuário não comprova identidade.
3. O administrador autenticado redefine a senha no controle de usuários existente. O backend invalida as sessões do usuário alterado e registra a alteração sem a senha.
4. Se a empresa usar uma senha temporária, definir com o responsável um canal privado já aprovado para sua entrega; a aplicação não cria esse canal e não força expiração de senha temporária nesta fase. Solicitar a troca própria imediatamente após a entrada. Como evolução, adotar um fluxo de uso único/expiração depois de validar o canal e seus requisitos.
5. Confirmar que o usuário recuperou o acesso e revisar sessões/incidentes relacionados, sem publicar credenciais no chamado.

## Último administrador sem acesso

O aplicativo não oferece endpoint público ou atalho por código de instalação para recuperar o último administrador. O `COMPAC_SETUP_TOKEN` serve somente ao primeiro cadastro, quando ainda não existe usuário; ele não é chave mestra e não deve reabrir o cadastro inicial.

Uma recuperação excepcional exige intervenção autorizada de quem administra a infraestrutura, tratada como mudança de alto risco:

1. Registrar o incidente, confirmar identidade e autoridade do solicitante por canal/contrato previamente reconhecido e obter aprovação da empresa. Não basta uma solicitação em chat sem verificação.
2. Identificar a instância e o banco corretos pelos identificadores não secretos; preservar evidências e verificar possibilidade de comprometimento. Nenhum script deve escolher outro banco por conveniência.
3. Obter backup consistente e provar sua restauração em ambiente independente. Definir responsável, janela, acompanhamento e reversão antes de qualquer alteração no banco real.
4. Preparar e revisar o procedimento específico de redefinição de **um administrador existente**, mantendo o algoritmo compatível. Conferir previamente o ID, o papel ADMIN e a situação da conta. Não excluir usuários, limpar tabelas ou recriar a operação para recuperar acesso.
5. Ensaiar a redefinição em dados descartáveis. A operação de produção, quando especificamente autorizada, precisa atualizar o hash, revogar todas as sessões daquela conta e registrar auditoria sem segredo na mesma transação. Senhas devem ser recebidas por entrada privada, nunca como argumento/SQL literal/histórico de terminal. O procedimento de intervenção excepcional não está automatizado nesta fase.
6. Validar o login e a troca própria, encerrar o acesso excepcional, revisar os eventos e documentar a causa e as medidas preventivas. Tratar qualquer exposição de credencial como incidente separado.

## Limites e prevenção

- Manter mais de um administrador nominal autorizado, com contas individuais e revisão periódica. A regra da aplicação impede o administrador de remover o próprio acesso, mas não substitui o processo de continuidade da empresa.
- Os eventos de falha usam hashes dos identificadores; são pseudônimos, não anonimização garantida. A retenção operacional dos eventos de auditoria deve ser definida pela empresa. Os contadores transitórios expirados são removidos durante as tentativas de autenticação.
- A identificação da origem ainda usa o host observado pelo servidor. Headers `X-Forwarded-For`/`X-Real-IP` são ignorados. A topologia das proxies da hospedagem deve ser validada antes de alterar essa confiança; visitantes atrás da mesma proxy podem compartilhar o limite de origem.
- Nenhum envio automático de e-mail, fornecedor pago, MFA ou novo serviço de identidade foi adicionado. Esses canais exigem requisitos e autorização próprios.
