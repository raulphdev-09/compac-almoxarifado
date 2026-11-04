# Scripts da auditoria COMPAC

Estes scripts geram dados fictícios para observar o comportamento da base auditada. Não implementam correções na aplicação nem constituem uma suíte de aprovação das funcionalidades futuras. Os probes de bugs retornam evidências do comportamento incorreto atual.

Execute na raiz do repositório, com as dependências existentes, Python sem `-O` e Playwright/Chromium para os scripts de navegador. No ambiente gerenciado, permita rede de loopback para TestClient/Uvicorn; isso não exige acesso a banco remoto.

```sh
.venv/bin/python scripts/audit_baseline.py --output artifacts/audit-baseline.json
.venv/bin/python scripts/audit_security.py > artifacts/audit-security.json
.venv/bin/python scripts/audit_operations.py > artifacts/audit-operations.json
node scripts/audit_frontend.cjs > artifacts/audit-frontend.log
node scripts/audit_dates.cjs > artifacts/audit-dates.log
```

Crie `artifacts/` antes de redirecionar saídas, se a pasta não existir. Os scripts Python recusam modo otimizado para manter validações essenciais. Baseline e segurança sempre removem o alvo PostgreSQL herdado do processo e geram SQLite temporário; operações faz o mesmo por padrão. Nenhum deles lê `.env` ou usa o arquivo real `.data/compac.db`.

`audit_operations.py` também aceita `COMPAC_OPERATION_AUDIT_PG_URL`, exclusivamente igual à DSN LOCAL fixa `postgresql://compac_audit@127.0.0.1:55439/compac_audit`. Exige o cluster descartável descrito em `docs/VALIDACAO_POSTGRESQL.md`; cria e remove somente seu schema aleatório. O cluster foi encerrado após a auditoria. Não reusar um banco operacional nessa porta/nome.

Os scripts de navegador iniciam Uvicorn apenas em loopback, porta 8824, com banco temporário e variáveis de produção desabilitadas. Execute-os em sequência para não disputar a porta. Usam Chromium em `/usr/bin/chromium` e Playwright acessível ao Node. Capturas/JSON de novas execuções vão para `artifacts/audit-frontend/`, ignorada pelo Git. O probe de tabelas intercepta o catálogo no navegador para fornecer linhas sintéticas; não grava 10 mil materiais no banco.

Os scripts PostgreSQL originais de benchmark/restore estão preservados como `.py.txt` em `docs/evidencias/postgresql/`, junto dos planos e resultados. São transcrições dos experimentos locais; dependem do cluster e dos caminhos de ferramentas temporários descritos no relatório. Sua fixture de volume não representa o balanço físico de empréstimos de uma empresa.

Evidências da execução original: `docs/evidencias/`. Reexecutar pode gerar tempos diferentes; não sobrescrever resultados históricos para simular melhoria. Uma nova medição precisa registrar o commit, método, ambiente e dados usados.
