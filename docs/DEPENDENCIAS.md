# Auditoria de dependências — COMPAC

Data de referência: 2026-11-04 (America/Sao_Paulo). Auditoria somente de consulta pública, sem alterações no projeto, ambiente virtual ou produção.

## Método e resultado

- `requirements.lock`: 24 pacotes Python fixados por versão; os pacotes instalados em `.venv` coincidem com essas versões (pip também está instalado).
- OSV `POST https://api.osv.dev/v1/querybatch`: consulta de todos os pares nome/versão no ecossistema PyPI. Todas as respostas retornaram sem `vulns`.
- PyPI `GET https://pypi.org/pypi/{nome}/{versao}/json`: todos os pacotes/versões existem, possuem publicação anterior à data da auditoria, não estão integralmente retirados (`yanked=false`) e retornam `vulnerabilities=[]`.
- Resultado: nenhuma vulnerabilidade conhecida retornada por essas duas fontes para as versões consultadas. Não equivale a ausência garantida de vulnerabilidades ou análise do sistema operacional/imagens da hospedagem.
- `pip-audit` não está instalado; foi usada a consulta direta às fontes OSV/PyPI, sem instalar pacotes no ambiente compartilhado.

## Inventário consultado

| Pacote | Versão | Publicação PyPI (UTC) | Advisory retornado |
|---|---|---|---|
| annotated-doc | 0.0.5 | 2026-07-28T13:50:57.239109Z | Nenhum |
| annotated-types | 0.8.0 | 2026-07-23T20:16:12.938651Z | Nenhum |
| anyio | 4.15.1 | 2026-09-05T10:42:37.923487Z | Nenhum |
| certifi | 2026.10.23 | 2026-10-23T11:36:14.763067Z | Nenhum |
| click | 8.5.0 | 2026-08-26T13:33:12.928043Z | Nenhum |
| fastapi | 0.162.0 | 2026-10-23T18:47:31.734776Z | Nenhum |
| h11 | 0.16.0 | 2025-04-24T03:35:24.344199Z | Nenhum |
| httpcore | 1.0.9 | 2025-04-24T22:06:20.566605Z | Nenhum |
| httpx | 0.28.1 | 2024-12-06T15:37:21.509172Z | Nenhum |
| idna | 3.20 | 2026-09-17T14:11:03.168153Z | Nenhum |
| iniconfig | 2.3.1 | 2026-10-06T22:48:36.959685Z | Nenhum |
| opentelemetry-api | 1.45.2 | 2026-10-29T17:29:06.955093Z | Nenhum |
| packaging | 26.3 | 2026-08-04T18:15:27.159957Z | Nenhum |
| pluggy | 1.7.0 | 2026-10-15T09:50:56.808462Z | Nenhum |
| psycopg | 3.3.6 | 2026-09-18T13:15:29.374570Z | Nenhum |
| psycopg-binary | 3.3.6 | 2026-09-18T13:15:36.605603Z | Nenhum |
| pydantic | 2.14.2 | 2026-10-29T16:37:10.181777Z | Nenhum |
| pydantic_core | 2.50.2 | 2026-10-29T16:31:28.258642Z | Nenhum |
| Pygments | 2.21.0 | 2026-08-17T08:02:44.912148Z | Nenhum |
| pytest | 9.2.0 | 2026-10-27T21:30:19.131148Z | Nenhum |
| starlette | 1.10.0 | 2026-10-24T15:04:10.371825Z | Nenhum |
| typing-inspection | 0.4.4 | 2026-08-12T12:37:24.648475Z | Nenhum |
| typing_extensions | 4.16.0 | 2026-07-02T08:40:04.659120Z | Nenhum |
| uvicorn | 0.54.0 | 2026-09-25T06:52:35.829563Z | Nenhum |

## Riscos residuais observados no repositório

- Baixo: `requirements.lock` fixa versões mas não contém hashes dos artefatos. `render.yaml` instala com `pip install -r requirements.lock`, sem `--require-hashes`; integridade/proveniência dos artefatos depende do índice/TLS e do pipeline. Recomendar geração de hashes e atualização periódica com testes.
- Baixo: `pytest`, `httpx` e dependências de testes estão no mesmo conjunto de instalação de produção; separar dependências de desenvolvimento ao evoluir o pipeline, preservando testes e compatibilidade.
- Não auditados: CVEs da imagem/base do Render, OpenSSL/libpq embarcados por wheels, pacotes do sistema operacional, credenciais e configurações ao vivo. Não houve chamada a Render ou Neon.

## Evidência reproduzível

- `docs/evidencias/dependencias-osv.json`: resposta integral OSV.
- `docs/evidencias/dependencias-pypi.json`: metadados públicos resumidos por versão, datas, estado yanked e advisories.
- Escopo das fontes: o servidor pode atualizar advisories após esta consulta; repetir no CI a cada alteração de lock e periodicamente.
