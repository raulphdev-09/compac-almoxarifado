# Evidências da etapa zero

Todos os dados operacionais presentes são fictícios. Referência do código auditado: `6a24fa763995cc52322b7c618ef9f8b95cbb369d`, 4 de novembro de 2026. Nenhuma evidência foi extraída de dados/segredos de produção.

- `baseline-sqlite.json`: metadados, percentis de 30 amostras, bytes, SQLs, índices e ensaio de restauração; script `scripts/audit_baseline.py`.
- `rotas.json`: inventário de 37 rotas explícitas extraído da AST; não inclui montagem de estáticos e OpenAPI implícito.
- `seguranca.json`: respostas e contadores dos probes de segurança; script `scripts/audit_security.py`.
- `operacoes-sqlite.json` e `operacoes-postgresql.json`: reprodução de duplicação, unidade histórica, validação, empréstimo parcial e rollback; script `scripts/audit_operations.py`.
- `dependencias-osv.json` e `dependencias-pypi.json`: consulta pública por pacote/versão, sem advisories retornados naquele momento; ausência de advisory não é garantia de segurança.
- `interface/`: screenshots fictícios, cache/foco/contraste, catálogo de grande volume e default de data; scripts de auditoria de navegador e testes existentes.
- `postgresql/`: 15 planos EXPLAIN ANALYZE, resumo de tempos SQL, percentis de 20 amostras de API e comparação de dump/restore dos três schemas sintéticos. As fontes dos experimentos foram preservadas como `.py.txt` sem execução automática.

O PostgreSQL de teste foi criado e encerrado localmente. Os ensaios de backup/restauração não configuraram backups da COMPAC. Os scripts e relatórios diferenciam confirmação de controle, reprodução de bug, hipótese e funcionalidade ausente. Arquivos não são laudo de pentest/certificação WCAG ou aprovação de SLA.
