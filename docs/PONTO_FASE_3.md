# COMPAC — comparação facial experimental, Fase 3

Branch `feat/compac-ponto-fase3`, base `268f9ce`. Entrega incremental de comparação facial local, integrada ao terminal da Fase 2. **Continua restrita a testes supervisionados, sem homologação e sem substituir o ponto oficial.** Nenhuma publicação, migração remota, foto de empregado ou configuração de produção foi utilizada.

## Auditoria e decisão técnica

A aplicação usa FastAPI, Python 3.12, SQLite/PostgreSQL e HTML/CSS/JavaScript. Funcionários, obras, perfis ADMIN/OPERADOR/CONSULTA, auditoria, transações e idempotência já existem. A Fase 2 oferece credenciais próprias do terminal, vínculo à obra, câmera local e autorização simulada, mas não comparação de identidade.

Foi escolhido `opencv-python-headless==4.12.0.88`, com YuNet para detectar/alinhar o rosto e SFace para comparar duas referências. Funciona em CPU no ambiente Python 3.12 verificado, sem serviço externo de identificação ou dependência de API paga. Dlib/face_recognition exigiria maior esforço de compilação e revisão dos modelos/licenças; não foi incorporado.

O código OpenCV usa Apache 2.0; os arquivos do modelo YuNet são distribuídos sob MIT, e SFace sob Apache 2.0. As [licenças copiadas](licencas/README.md) e as URLs/checksums fixados acompanham esta entrega. Essa verificação de distribuição não substitui a avaliação de direitos, finalidade e base legal para os dados usados pela organização.

Os modelos vêm da revisão imutável `48b10fa505aeb51fbd127fc60a5c660040e823b7` do [OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/48b10fa505aeb51fbd127fc60a5c660040e823b7/models). A instalação é uma ação explícita; a API nunca baixa pesos nem aceita um substituto que aprove automaticamente rostos.

| Modelo | Bytes | SHA-256 |
| --- | ---: | --- |
| YuNet `face_detection_yunet_2023mar.onnx` | 232589 | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| SFace `face_recognition_sface_2021dec.onnx` | 38696353 | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` |

## Fluxo entregue

1. Em modo `facial`, ADMIN consulta uma matrícula do cadastro existente e envia uma referência JPEG/PNG, com confirmação de autorização organizacional, descrição da base legal e validade de 1 a 90 dias. O backend exige exatamente um rosto e qualidade mínima antes de normalizar a imagem e remover metadados.
2. A referência normalizada fica criptografada por AES-GCM, com nonce aleatório e contexto vinculado ao funcionário/versão. A chave é externa ao banco. Não há URL de foto, endpoint público de leitura ou persistência de vetores faciais.
3. O terminal ativado informa matrícula e captura um JPEG somente após ação explícita do usuário e confirmação de supervisão. A imagem é temporária, validada e comparada no servidor. Não é salva em arquivo, banco, cache, log ou armazenamento do navegador pela aplicação.
4. O backend valida tamanho/formato, exige um rosto, verifica funcionário ativo e obra do dispositivo, descriptografa a referência e compara representações SFace em memória. Uma detecção isolada ou `face_verified=true` não autoriza marcação.
5. Correspondência confirmada gera uma autorização de sessenta segundos, uso único, vinculada ao dispositivo, funcionário e versão da referência. Após a inferência, o sistema revalida credencial, emissor ADMIN, obra, funcionário e versão sob a transação de escrita.
6. A marcação utiliza horário do servidor e idempotência. O método é `FACIAL_EXPERIMENTAL`, o resultado `CORRESPONDENCIA_CONFIRMADA`, e `is_test=1`. Registros simulados mantêm seus valores anteriores. Nenhuma marcação original é editada ou apagada.

Matrículas desconhecidas, inativas, sem referência válida, de outra obra e identidade não confirmada recebem o mesmo erro genérico. A captura é validada antes da busca da matrícula, para que uma imagem sem rosto não revele qual cadastro tem referência. Não há listagem de funcionários ou históricos no terminal. Limites de tentativas persistem, inclusive nas falhas.

Ausência/múltiplos rostos, baixa qualidade, câmera negada/ausente, rede indisponível, modelo/chave inválido e comparador ocupado geram erro seguro, sem aprovação automática. No modo `demo`, a câmera continua somente local e a autorização continua explicitamente `SIMULADO`; autorizações não migram entre modos.

## Referências, exclusão e alternativa

Atualização ou exclusão da referência invalida autorizações pendentes da versão anterior, preservando marcações e auditorias. ADMIN pode excluir individualmente ou usar **Excluir referências expiradas** para a limpeza auditada em lote. O lote inteiro é transacional: falha de auditoria desfaz a exclusão.

`retention_days` define a validade e a data prevista para exclusão conforme a política da organização. Expiração bloqueia imediatamente o uso, mas **esta versão não agenda limpeza automática**: o responsável deve executar a exclusão das expiradas. Backups e réplicas têm sua própria política de retenção/exclusão; remover do banco atual não apaga backups históricos. Não manter referências após a finalidade/validade aprovada sem executar o procedimento.

Se a pessoa não puder usar biometria, se revogar a referência ou se o comparador falhar, seguir o procedimento alternativo oficial da empresa. Não converter silenciosamente uma falha facial em marcação aprovada. A demonstração local com dados fictícios permanece disponível como modo separado, e não como comprovação de identidade.

## Segurança e limites operacionais

- Uso permitido somente com `COMPAC_ENV=development` ou `test`, `COMPAC_ATTENDANCE_MODE=facial` e `COMPAC_FACE_SUPERVISED=1`. Render, produção e PostgreSQL remoto continuam bloqueados. Não se habilita o recurso apenas publicando esta branch.
- HTTPS obrigatório fora de localhost; cookie do terminal HttpOnly/SameSite Strict, escopo restrito, TTL e revogação da Fase 2 preservados. O TLS de proxy só é confiado por configuração do servidor. Foto/obra/horário/resultado do navegador não substituem validação do backend.
- JPEG/PNG único de até 2 MiB, máximo 4 megapixels e 4096 pixels por lado, mínimo 96; processamento reduzido a até 1280 pixels. Imagem comprimida com dimensões excessivas, formatos alternativos e imagens animadas são recusados. O corpo JSON é limitado a 3 MiB; erros de validação não devolvem a imagem enviada.
- Modelo/limiar/criptografia indisponível falha fechado. A configuração não aceita limiar igual ou inferior a `0.363`. O padrão experimental é cosine `0.5`, **não calibrado para COMPAC**. O limiar upstream de referência é de benchmark, não garantia de taxa de falso aceite.
- Detecção exige um rosto com dimensões/landmarks mínimos; representações e scores são somente locais à comparação. Modelos nativos mutáveis são protegidos por lock. Inferência e consultas das rotas assíncronas ocorrem fora do event loop, e o processamento pesado fica fora da transação de escrita.
- Quotas podem ser compartilhadas por conexões atrás do mesmo proxy e por emissor; dimensionar antes de teste com vários terminais. Não se confia em `X-Forwarded-For` arbitrário.
- Captura não fica em fila offline. Resposta de marcação incerta é repetida com a mesma chave, sem recapturar. Recarregar/encerrar tentativa exige conferência pelo supervisor. A aplicação não controla eventuais logs de corpo de requisição em infraestrutura externa; devem permanecer desabilitados.

**YuNet/SFace não implementam prova de vida/PAD.** Uma foto ou vídeo pode enganar o comparador. Mesmo uma correspondência confirmada aqui não comprova presença física; o protótipo continua supervisionado. Não foi implementado mecanismo fictício de liveness nem vigilância contínua.

## Migração preservando histórico

A revisão `004_attendance_face` só adiciona:

- `attendance_face_references`: referência criptografada separada dos dados administrativos, sua versão, responsável, base informada e validade.
- `attendance_face_grants`: vínculo da autorização ao dispositivo, versão da referência e algoritmo.
- `attendance_facial_records`: marcações faciais experimentais, com UID/autorizações únicos e FKs.

As tabelas de estoque, funcionários, obras e registros antigos não são reconstruídas nem alteradas. As revisões SQL/checksums 001, 002 e 003 foram preservadas. A separação física evita reclassificar antigos registros simulados como faciais ou enfraquecer suas restrições. As APIs administrativas de histórico unem as duas origens, preservam os filtros e usam `record_uid` como identificador global; IDs numéricos são locais a cada tabela.

Runner, índices, checksums, sequência e validação estrutural são os existentes, com testes para os dois motores. Falha aplica rollback integral. Para uma futura implantação autorizada: backup/restauração verificável, inspeção `python -m app.migrate --check`, aplicação administrativa `python -m app.migrate --apply` e nova inspeção antes de publicar. **Não executar esses comandos contra produção nesta etapa.** Não existe rollback destrutivo de dados ou histórico nesta entrega.

## Executar localmente

No diretório do projeto, com a `.venv` existente:

```sh
.venv/bin/python -m pip install -r requirements-face.txt
.venv/bin/python scripts/install_face_models.py
```

As dependências de comparação são opcionais; não foram adicionadas ao `requirements.txt` do almoxarifado. Os pesos e a configuração ficam fora de `app/static`, em `.data/face-models` por padrão, sem commit. O script confere tamanho/checksum e copia as licenças dos modelos.

Para um ambiente local descartável, inicie o servidor com uma chave privada persistente local, sem imprimi-la. O exemplo não lê nem altera configurações remotas:

```sh
env -u DATABASE_URL -u COMPAC_REQUIRE_POSTGRES -u RENDER -u COMPAC_PUBLIC_URL -u RENDER_EXTERNAL_URL -u COMPAC_SETUP_TOKEN .venv/bin/python - <<'PY'
import base64, os
from pathlib import Path
private = Path('.data/facial-demo.key')
private.parent.mkdir(mode=0o700, exist_ok=True)
if not private.exists():
    fd = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(base64.urlsafe_b64encode(os.urandom(32)).decode())
os.environ.update(
    COMPAC_FACE_KEY=private.read_text().strip(),
    COMPAC_ENV='development', COMPAC_ATTENDANCE_MODE='facial',
    COMPAC_FACE_SUPERVISED='1', COMPAC_COOKIE_SECURE='0',
    COMPAC_DB='/tmp/compac-ponto-fase3-demo.db',
)
from app.serve import main
main()
PY
```

Guardar essa chave separadamente do banco; perder/trocar a chave torna as referências existentes ilegíveis. Não imprimir em logs/chat, incluir em commit ou copiar para a pasta pública. Rotação de chave de uma instalação com dados requer um procedimento próprio; não há rotação automática nesta entrega.

Abra `http://localhost:8000`, crie ADMIN, obra e funcionário fictícios. Em Gestão de Pessoal → Terminais de ponto · teste, consulte a matrícula e cadastre **somente uma imagem sintética** de `tests/fixtures/faces/` para reproduzir a demonstração sem fotos reais. Informe uma justificativa de teste, validade e confirmação. Depois crie/ative o terminal em outro perfil/navegador e permita a câmera. Uma câmera artificial geométrica será recusada; comparação positiva precisa mostrar a identidade sintética correspondente, não qualquer rosto.

Não usar foto de empregado nesse exemplo sem autorização organizacional e base legal adequada. A declaração de formulário registra a confirmação do responsável; um checkbox não estabelece por si só a base legal. O procedimento oficial da empresa continua obrigatório durante os testes.

## APIs novas e integração

| API | Acesso e função |
| --- | --- |
| GET `/api/v1/attendance/face-reference?registration=...` | ADMIN; metadados, sem fotografia/ciphertext |
| POST `/api/v1/attendance/face-reference` | ADMIN; referência validada, autorização/base legal e validade |
| DELETE `/api/v1/attendance/face-reference?registration=...` | ADMIN; exclui referência e invalida pendências |
| POST `/api/v1/attendance/face-references/purge-expired` | ADMIN; exclusão transacional auditada das expiradas |
| POST `/api/v1/attendance/terminal/verify-face` | Cookie do dispositivo; captura temporária e emissão de autorização |
| POST `/api/v1/attendance/terminal/mark` | Existente; aceita autorização facial somente no modo correspondente |

`verify-face` recebe `registration`, `image_base64` puro e `acknowledgement=VERIFICACAO_FACIAL_SUPERVISIONADA`. Referência recebe os campos da matrícula/imagem, `authorization_basis` (20–500 caracteres úteis), `retention_days` inteiro (1–90) e `acknowledgement=AUTORIZACAO_ORGANIZACIONAL_E_BASE_LEGAL_CONFIRMADAS`. Campos extras são recusados. A evidência de verificação é gerada pelo servidor, nunca um booleano do frontend.

## Arquivos criados e alterados

| Arquivo criado | Função |
| --- | --- |
| `app/attendance/face_engine.py` | Validação/normalização de imagem, YuNet/SFace local, hashes, decisão e criptografia autenticada |
| `app/attendance/face.py` | Referências ADMIN, expurgo, captura/verificação e marcação facial, revalidação e auditoria |
| `requirements-face.txt`, `scripts/install_face_models.py` | Dependências opcionais e instalação explícita dos pesos fixados |
| `tests/test_attendance_faces.py` | Contratos de segurança/transação com adaptador exclusivo de teste |
| `tests/test_attendance_face_migrations.py` | Revisão 004, preservação, rollback, restrições e estrutura |
| `tests/test_face_engine.py` | Imagens, criptografia, adaptador e rejeição nativa de pixels sem rosto |
| `tests/test_face_synthetic_integration.py`, `tests/fixtures/faces/` | Aceites/rejeições e API com modelos reais e duas identidades inteiramente sintéticas |
| `tests/browser_facial_smoke.cjs`, `tests/facial_browser_server.py` | Interface com câmera artificial/adaptador de teste e cenário nativo de rejeição |
| `docs/PONTO_FASE_3.md`, `docs/evidencias/ponto-fase3-validacao.md`, `docs/evidencias/ponto-fase3/`, `docs/licencas/` | Operação, evidências, capturas e licenças |

| Arquivo alterado | Função |
| --- | --- |
| `app/migrations.py` | Acrescenta revisão 004 sem mudar os SQL anteriores |
| `app/attendance/service.py` | Guardas de experimento e demonstração separadas |
| `app/attendance/device.py` | Credenciais partilhadas pelos dois modos, status e despacho seguro de marcação |
| `app/attendance/routes.py` | Status Fase 3, administração compartilhada e histórico unificado |
| `app/main.py` | Registra novas rotas |
| `app/static/attendance-terminal.html`, `.css`, `.js` | Captura temporária, modo facial, resultado verdadeiro e feedback |
| `app/static/attendance-admin.html`, `.css`, `.js` | Cadastro/exclusão da referência, declaração, validade e expurgo |
| `tests/test_migrations.py`, `tests/test_attendance_migrations.py`, `tests/test_attendance_device_migrations.py` | Mantém regressões compatíveis com quatro revisões |
| `tests/test_attendance_terminal_pages.py` | Continua proibindo persistência; modo facial agora permite captura explícita |
| `README.md` | Liga a entrega e evidências |

## Validação e pendências

A suíte consolidada passou **623 testes em SQLite/PostgreSQL**, incluindo comparação e API com modelos reais e identidades sintéticas. Os [resultados e comandos](evidencias/ponto-fase3-validacao.md) distinguem testes de contrato com adaptador, testes nativos e testes de navegador. Fluxos de almoxarifado, autorização e PWA passaram na regressão. Não foram usadas fotografias reais.

Os testes sintéticos positivos/negativos **não medem FAR/FRR representativos**. Antes de um piloto com pessoas reais: aprovação organizacional/jurídica, conjunto autorizado e representativo, calibração separada da validação, avaliação de falsos aceites/rejeições por luz/câmera/distância e grupos, acessibilidade, supervisão, alternativa e política de exclusão. A ausência de PAD permanece uma restrição de teste, não foi solucionada por escolher um limiar maior.

Dashboard, escalas, horas/atrasos/faltas, relatórios e correções auditadas são a Fase 4. Qualidade/implantação autorizada é a Fase 5. Importação de materiais/documentos, PDFs/WhatsApp e otimizações separadas não fazem parte desta entrega.

Uso oficial exige avaliação específica dos requisitos trabalhistas brasileiros de registro de jornada e da LGPD, incluindo base legal para biometria sensível, finalidade, minimização, segurança, retenção/exclusão, direitos dos titulares, alternativa e responsabilidade. Não se afirma homologação nem adequação automática a substituir o ponto oficial.
