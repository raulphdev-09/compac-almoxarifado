# Retratos inteiramente sintéticos — somente testes

`synthetic-a.jpg` e `synthetic-b.jpg` representam dois adultos **inteiramente fictícios**. Foram gerados por `image_gen` nesta sessão em 8 de novembro de 2026, a partir de descrição textual de retratos frontais distintos. Não foram usadas fotografias de empregados, de pessoas reais, de celebridades, de bancos de imagens ou de câmera física. Os arquivos não representam pessoas cadastradas na COMPAC.

Quadro original gerado: `exec-4566a90d-f2bd-4bca-a3c4-d872e38b82d7.png`. Os dois painéis foram separados e reduzidos a JPEG de até 512 pixels para fixtures pequenas. Não há EXIF ou outros metadados pessoais.

| Arquivo | Bytes | SHA-256 |
| --- | ---: | --- |
| `synthetic-a.jpg` | 44258 | `b3cda70c582b81d71ceb0bfa672eceba42dab607ca59497ad97f73f7791938aa` |
| `synthetic-b.jpg` | 35744 | `71b8651a03ed7548154a0e76a0eb6a9bcdf2ab165e28855cfdb0ed3fdae75dca` |

Os testes opt-in `tests/test_face_synthetic_integration.py` executam os modelos oficiais YuNet/SFace, sem substituir o comparador por um mock. Verificam pares da mesma identidade sintética, variação leve de brilho/tamanho, pares distintos e múltiplos rostos. Também cobrem o fluxo real de referência criptografada → rejeição de outra identidade sintética → verificação → marcação idempotente pela API.

Executar com os modelos previamente instalados pelo comando documentado:

```sh
COMPAC_FACE_TEST_MODELS_DIR="$PWD/.data/face-models" .venv/bin/python -m pytest -q tests/test_face_synthetic_integration.py
```

Esses poucos casos controlados são evidência de integração e decisões do motor. **Não medem FAR/FRR representativos, não calibram o limiar, não validam condições de canteiro e não demonstram proteção contra apresentação de fotografias ou vídeos.** Os testes não autorizam o uso de imagens reais nem a substituição do ponto oficial. As licenças dos modelos continuam independentes dessas fixtures e são preservadas pelo instalador.
