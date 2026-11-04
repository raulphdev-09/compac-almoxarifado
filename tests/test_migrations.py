import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from app.db import connect, init_db, SCHEMA
from app.migrations import CHECKSUM, REVISION, migrate, statements, status, table_exists


LEGACY_TABLES = [s.split('(')[0].split()[-1] for s in SCHEMA.split(';') if s.strip().startswith('CREATE TABLE')]


def legacy_snapshot():
    with connect() as db:
        return {name: sorted(json.dumps(dict(row), sort_keys=True) for row in db.execute(f'SELECT * FROM {name}'))
                for name in LEGACY_TABLES}


def remove_test_migration():
    # Only called after client_factory created a disposable database/schema.
    with connect(write=True) as db:
        for name in ('idempotency_requests', 'auth_attempts', 'schema_migrations'):
            db.execute(f'DROP TABLE {name}')


def test_legacy_data_preserved_and_migration_repeatable(admin, catalog):
    before = legacy_snapshot()
    remove_test_migration()
    init_db(allow_migrations=True)
    assert legacy_snapshot() == before
    init_db(allow_migrations=True)
    assert legacy_snapshot() == before
    with connect() as db:
        assert status(db) == {'revision': REVISION, 'applied': True, 'checksum_valid': True}
        assert db.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0] == 1


def test_production_start_requires_explicit_migration(client_factory, monkeypatch):
    remove_test_migration()
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.setenv('COMPAC_SETUP_TOKEN', 'disposable-test-only')
    with pytest.raises(RuntimeError, match='Migração pendente'):
        init_db()
    with connect() as db:
        assert not table_exists(db, 'schema_migrations')
        assert not table_exists(db, 'auth_attempts')
    init_db(allow_migrations=True)
    init_db()  # Production can now start without applying any pending DDL.


def test_migration_failure_rolls_back_all_ddl(client_factory):
    remove_test_migration()
    with patch('app.migrations.statements', side_effect=lambda db: statements(db) + ['INVALID SQL FOR AUDIT TEST']):
        with pytest.raises(Exception):
            init_db(allow_migrations=True)
    with connect() as db:
        assert not table_exists(db, 'schema_migrations')
        assert not table_exists(db, 'idempotency_requests')
        assert not table_exists(db, 'auth_attempts')


def test_migration_checksum_mismatch_fails_closed(client_factory):
    with connect(write=True) as db:
        db.execute('UPDATE schema_migrations SET checksum=? WHERE version=?', ('wrong', REVISION))
    with pytest.raises(RuntimeError, match='Checksum'):
        init_db()


def test_recorded_migration_missing_table_fails_closed(client_factory):
    with connect(write=True) as db:
        db.execute('DROP TABLE auth_attempts')
    with pytest.raises(RuntimeError, match='incompleto'):
        init_db()


def test_recorded_migration_requires_primary_key(client_factory):
    with connect(write=True) as db:
        db.execute('DROP TABLE auth_attempts')
        db.execute('CREATE TABLE auth_attempts(id INTEGER,account_hash TEXT,origin_hash TEXT,attempted_at INTEGER)')
    with pytest.raises(RuntimeError, match='chave divergente'):
        init_db()


def test_recorded_migration_requires_throttle_indexes(client_factory):
    with connect(write=True) as db:
        db.execute('DROP INDEX auth_attempts_account_time')
    with pytest.raises(RuntimeError, match='índices'):
        init_db()


def test_check_absent_sqlite_does_not_create_database(tmp_path):
    target = tmp_path / 'missing' / 'check.db'
    environment = {**os.environ, 'COMPAC_DB': str(target)}
    environment.pop('DATABASE_URL', None)
    result = subprocess.run([sys.executable, '-m', 'app.migrate', '--check'], env=environment, capture_output=True, text=True)
    assert result.returncode == 1
    assert json.loads(result.stdout)['applied'] is False
    assert not target.parent.exists()
