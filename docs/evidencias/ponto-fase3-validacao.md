# Validação — comparação facial experimental, Fase 3

Data: 8 de novembro de 2026. Branch `feat/compac-ponto-fase3`, base `268f9ce`. Bancos SQLite temporários e schemas descartáveis em PostgreSQL 17.11 local. Nenhum banco remoto, publicação, foto de pessoa real ou configuração de produção foi usado.

## Suíte completa

```sh
COMPAC_TEST_DATABASE_URL=postgresql://compac_audit@127.0.0.1:55439/compac_audit COMPAC_FACE_TEST_MODELS_DIR="$PWD/.data/face-models" .venv/bin/python -m pytest -q
```

**623 passed, 1 warning em 176,60 segundos**, incluindo SQLite, PostgreSQL local e os testes nativos com identidades sintéticas. O único aviso é a depreciação conhecida Starlette TestClient/httpx.

A URL acima é somente do servidor local descartável desta sessão; provisionar uma instância própria para repetir. Omitir a variável PostgreSQL executa somente SQLite. As dependências/modelos opcionais devem ser instalados conforme [PONTO_FASE_3.md](../PONTO_FASE_3.md); testes opcionais são ignorados quando não estão disponíveis.

## Cobertura e classificação da evidência

- **Contratos com adaptador exclusivo de testes:** ADMIN/dispositivo, referência criptografada, quatro marcações, dados mínimos, desconhecido/inativo/outra obra, autorização vinculada a versão/dispositivo, revogação, TTL, idempotência e concorrência. Não medem precisão biométrica.
- **Transações:** falha de auditoria desfaz referência, emissão, marcação, exclusão individual ou lote de expiradas. Troca de obra/cadastro, encerramento da sessão administrativa, rotação/revogação do dispositivo e alteração da referência durante inferência impedem confirmação com estado desatualizado.
- **Privacidade/erros:** imagem sem rosto é recusada antes de consultar a matrícula, com resposta igual para matrícula válida/desconhecida/inativa/sem referência. Corpo limitado, campos extras/horário/obra/booleano facial recusados, erros sem eco da imagem, metadados sem foto/ciphertext e histórico inacessível ao terminal.
- **Validação/criptografia:** JPEG/PNG, dimensões, limites, imagens truncadas/animadas, EXIF removido, nenhum/múltiplos rostos, qualidade, resultado inválido, modelos ausentes/corrompidos, limiar inválido, nonce aleatório, contexto funcionário/versão e adulteração/chave errada.
- **Migração:** revisão 004 aditiva, SQL/checksums 001/002/003 congelados, preservação integral de cadastros/históricos/idempotência, reaplicação, rollback, estrutura/índices/FKs/uniqueness e restrições de método/resultado/is_test.
- **Regressão:** suíte anterior de estoque, empréstimos/devoluções, movimentações, autenticação, permissões, auditoria e demonstração permanece incluída.

## Motor real, sem adaptador

`tests/test_face_synthetic_integration.py` usa os modelos oficiais fixados e duas identidades adultas **inteiramente sintéticas**, geradas nesta sessão. [Origem, hashes e limites](../../tests/fixtures/faces/README.md) acompanham as imagens pequenas, sem EXIF. Não são fotos de empregados nem de pessoas reais.

No alvo SQLite/PostgreSQL, **9 testes passaram**: quatro pares positivos (mesma identidade e variantes leves de brilho/tamanho), dois pares negativos (identidades distintas nos dois sentidos), detecção com dois rostos e fluxo da API nos dois motores. A API real registrou referência criptografada, recusou a identidade distinta, confirmou a variante correspondente e manteve uma marcação no reenvio.

O teste nativo adicional de imagem geométrica retornou ausência de rosto. Não houve aceitação automática para compensar falta de modelo ou detecção.

Esses pares controlados demonstram integração e decisões do comparador, **não são estimativas representativas de FAR/FRR**, calibração COMPAC, prova de vida ou validação em canteiro. O limiar experimental permanece 0.5; não se declara percentual de precisão.

## Navegador

Chromium/Playwright, câmera artificial e bancos locais descartáveis:

```sh
node tests/browser_facial_smoke.cjs
COMPAC_TERMINAL_TEST_PORT=8847 node tests/browser_terminal_smoke.cjs
COMPAC_TEST_PORT=8848 COMPAC_TEST_ARTIFACTS=/tmp/compac-fase3-warehouse-ui node tests/browser_smoke.cjs
env -u PWA_BASE_URL PWA_TEST_PORT=8849 node tests/pwa_smoke.cjs
```

- **Facial PASS:** cadastro/consulta/exclusão da referência, declaração e limpeza do arquivo selecionado; captura JPEG temporária; resposta correta de correspondência; reenvio com a mesma chave sem recaptura; duas marcações preservadas, exclusão impedindo novo ponto e histórico anterior intacto; isolamento e desktop/celular. O cenário positivo de interface usa adaptador explicitamente exclusivo do servidor de testes. Um segundo cenário usa OpenCV nativo e recusa imagem geométrica sem rosto, sem gravar referência, autorização ou marcação.
- **Demo Fase 2 PASS:** câmera somente local, nenhuma imagem enviada, autorização simulada, reenvio/recuperação, câmera negada/ausente, revogação e isolamento. O suporte facial não transforma a demonstração em biometria.
- **Almoxarifado PASS:** conta inicial, material pelo formulário, entrada de estoque, chamado/comentário/status, telas e navegação desktop/celular sem erro JavaScript.
- **PWA PASS:** manifesto/ícones/instalação Chromium, cache limitado ao público, rejeição de GET/POST offline, formulário preservado, recuperação e atualização somente após confirmação.

Capturas inspecionadas: [administração](ponto-fase3/admin.png), [terminal desktop](ponto-fase3/terminal-desktop.png) e [terminal celular](ponto-fase3/terminal-celular.png). Somente dados fictícios e câmera artificial; nenhum código de ativação ou credencial aparece nas capturas.

## Revisão e verificações finais

Revisão independente de leitura confirmou os vínculos de credenciais/autorizações, revalidação após inferência, ausência de duplicação/perda de histórico, criptografia e expurgo. Os achados sobre resposta de matrícula, consulta síncrona na rota async e exclusão de expiradas foram corrigidos e cobertos por regressões. Sem bloqueadores remanescentes identificados.

Verificação sintática Python/JavaScript, `git diff --check`, `pip check`, hashes de modelos e fixtures e comparação literal dos SQL/checksums 001/002/003 com a base passaram. Pesos instalados somente em `.data/face-models`, excluído do Git, sem download no runtime da API.

## Riscos e pendências

Não foi testada câmera física, Safari/iOS nativo, instalação em obra, iluminação adversa, população representativa ou ataque de apresentação de foto/vídeo. YuNet/SFace não fornecem PAD. O procedimento supervisionado e o ponto oficial permanecem necessários. Não houve tratamento de fotos reais ou validação de base legal organizacional para empregados.

Expiração impede uso; exclusão das expiradas requer ação ADMIN, sem agendamento automático nesta fase. Backups têm política própria. Modelos/dependências são opcionais e falham fechado; perda da chave exige gestão específica das referências. Quotas por origem/emissor precisam de dimensionamento para vários terminais.

Dashboard/escalas/relatórios/ajustes, calibração operacional representativa e eventual implantação autorizada permanecem para as fases seguintes. Nenhuma garantia de homologação trabalhista ou adequação automática à LGPD é inferida destes testes.
