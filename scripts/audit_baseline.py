"""Read-only product audit against generated, disposable SQLite data only.

Run: .venv/bin/python scripts/audit_baseline.py --output artifacts/audit-baseline.json
No existing database, .env, cloud API, or production URL is read by this script.
"""
import argparse
import json
import math
import os
import platform
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if sys.flags.optimize:
    raise RuntimeError('Audit scripts require assertions; run Python without -O')


def percentile(values, fraction):
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 3)


def scenario(size, samples):
    # Keep direct/imported calls as safe as the CLI entry point.
    for key in ('DATABASE_URL', 'COMPAC_TEST_DATABASE_URL', 'RENDER', 'RENDER_EXTERNAL_URL',
                'COMPAC_SETUP_TOKEN', 'COMPAC_PUBLIC_URL', 'COMPAC_REQUIRE_POSTGRES'):
        os.environ.pop(key, None)
    from fastapi.testclient import TestClient
    from app.db import Database, connect
    from app.main import app, hash_password, now

    with tempfile.TemporaryDirectory(prefix='compac-audit-') as temp:
        os.environ['COMPAC_DB'] = str(Path(temp) / 'generated.db')
        os.environ['COMPAC_COOKIE_SECURE'] = '0'
        with TestClient(app, headers={'X-Compac-Client': 'web'}) as client:
            material_count = size // 10
            requisition_count = size // 10
            timestamp = now()
            with connect(write=True) as db:
                db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?)',
                           (1, 'audit', 'Auditoria fictícia', hash_password('Audit-Only-Discard-2026'), 'ADMIN', 1, timestamp))
                db.execute('INSERT INTO works VALUES(?,?,?,?)', (1, 'AUDIT', 'Obra fictícia', 'ATIVA'))
                db.execute('INSERT INTO categories VALUES(?,?,?)', (1, 'Categoria fictícia', ''))
                db.execute('INSERT INTO locations VALUES(?,?,?)', (1, 'Local fictício', 1))
                db.executemany('INSERT INTO materials(id,code,description,category_id,unit,minimum_stock,individualizable,status) VALUES(?,?,?,?,?,?,?,?)', [
                    (i, f'AUDIT-{i:05d}', f'Material fictício {i:05d}', 1, 'UN', 1, 0, 'ATIVO')
                    for i in range(1, material_count + 1)
                ])
                db.executemany('INSERT INTO balances VALUES(?,?,?)', [
                    (i, 1, size // material_count * 1000) for i in range(1, material_count + 1)
                ])
                db.executemany('INSERT INTO movements(type,material_id,quantity,destination_id,notes,user_id,created_at) VALUES(?,?,?,?,?,?,?)', [
                    ('ENTRADA', i % material_count + 1, 1000, 1, 'Dado fictício de auditoria', 1, timestamp)
                    for i in range(size)
                ])
                db.executemany('INSERT INTO audit(user_id,action,entity,record_id,details,created_at) VALUES(?,?,?,?,?,?)', [
                    (1, 'ENTRADA', 'movements', i + 1, '{}', timestamp) for i in range(size)
                ])
                db.executemany('INSERT INTO requisitions(id,work_id,requester_id,priority,status,notes,created_at) VALUES(?,?,?,?,?,?,?)', [
                    (i, 1, 1, 'NORMAL', 'PENDENTE', 'Fictícia', timestamp) for i in range(1, requisition_count + 1)
                ])
                db.executemany('INSERT INTO requisition_items(requisition_id,material_id,quantity) VALUES(?,?,?)', [
                    (i, (i - 1) % material_count + 1, 1000) for i in range(1, requisition_count + 1)
                ])
            with connect() as db:
                indexes = [dict(r) for r in db.execute("SELECT name,tbl_name,sql FROM sqlite_master WHERE type='index'")]
                query_plans = [dict(r) for r in db.execute('EXPLAIN QUERY PLAN SELECT * FROM requisition_items WHERE requisition_id=?', (1,))]

            assert client.post('/api/auth/login', json={'username': 'audit', 'password': 'Audit-Only-Discard-2026'}).status_code == 200
            results = []
            for path in ('/api/movements', '/api/requisitions', '/api/stock', '/api/dashboard', '/api/catalog/materials'):
                for _ in range(2):
                    assert client.get(path).status_code == 200
                timings = []
                for _ in range(samples):
                    started = time.perf_counter()
                    response = client.get(path)
                    timings.append((time.perf_counter() - started) * 1000)
                    assert response.status_code == 200
                calls = []
                execute = Database.execute
                def counted(self, sql, params=()):
                    calls.append(sql)
                    return execute(self, sql, params)
                with patch.object(Database, 'execute', counted):
                    response = client.get(path)
                results.append(dict(path=path, samples=samples, p50_ms=round(statistics.median(timings), 3),
                                    p95_ms=percentile(timings, .95), p99_ms=percentile(timings, .99),
                                    response_bytes=len(response.content), sql_statements=len(calls)))
            write_times = []
            for _ in range(samples):
                started = time.perf_counter()
                response = client.post('/api/movements', headers={'Idempotency-Key':str(uuid.uuid4())}, json={'type': 'ENTRADA', 'material_id': 1, 'quantity': 1, 'destination_id': 1})
                write_times.append((time.perf_counter() - started) * 1000)
                assert response.status_code == 201
            results.append(dict(path='POST /api/movements', samples=samples, p50_ms=round(statistics.median(write_times), 3),
                                p95_ms=percentile(write_times, .95), p99_ms=percentile(write_times, .99)))
            # Exercise a standard SQLite snapshot/restore on generated data only.
            source = sqlite3.connect(os.environ['COMPAC_DB'])
            restored = sqlite3.connect(str(Path(temp) / 'restored.db'))
            try:
                source.backup(restored)
                assert restored.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                tables = [r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
                equal = all(source.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() == restored.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() for table in tables)
                assert equal
            finally:
                source.close()
                restored.close()
            return dict(initial_movements=size, materials=material_count, requisitions=requisition_count,
                        loans=0, expenses=0, tickets=0, results=results, indexes=indexes,
                        requisition_item_query_plan=query_plans, sqlite_snapshot_restore='all_tables_equal')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='artifacts/audit-baseline.json')
    parser.add_argument('--samples', type=int, default=30)
    args = parser.parse_args()
    if not 10 <= args.samples <= 200:
        parser.error('--samples must be between 10 and 200')
    # Prevent any inherited production target from reaching the application.
    for key in ('DATABASE_URL', 'COMPAC_TEST_DATABASE_URL', 'RENDER', 'RENDER_EXTERNAL_URL',
                'COMPAC_SETUP_TOKEN', 'COMPAC_PUBLIC_URL', 'COMPAC_REQUIRE_POSTGRES'):
        os.environ.pop(key, None)
    report = dict(timestamp=datetime.now(ZoneInfo('America/Sao_Paulo')).isoformat(),
                  commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  python=platform.python_version(), sqlite=sqlite3.sqlite_version,
                  method='warmed sequential in-process TestClient requests; no external network, not a load test',
                  scenarios=[scenario(size, args.samples) for size in (100, 1000, 10000)])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'scenarios'}, ensure_ascii=False))
    for case in report['scenarios']:
        print(json.dumps({k: v for k, v in case.items() if k not in ('indexes',)}, ensure_ascii=False))
    print(f'Output: {output}')


if __name__ == '__main__':
    main()
