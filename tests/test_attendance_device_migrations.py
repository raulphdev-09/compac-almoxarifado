import json
import sqlite3
from unittest.mock import patch

import psycopg
import pytest

from app.db import connect, init_db
from app.migrations import (BASE_CHECKSUM, ATTENDANCE_CHECKSUM, ATTENDANCE_REVISION,
                            REVISION, SQL, status, statements, table_exists)


TABLES = ('attendance_device_authorizations', 'attendance_device_sessions', 'attendance_activation_codes')


def previous_revision():
    with connect(write=True) as db:
        for table in TABLES:
            db.execute('DROP TABLE ' + table)
        db.execute('DELETE FROM schema_migrations WHERE version=?', (REVISION,))


def test_original_migration_checksums_remain_frozen():
    assert BASE_CHECKSUM == 'c3d1fa36db29b2b5bca9daa9a1ee329b94909e1f1d3a53bc248a05bfa5040b20'
    assert ATTENDANCE_CHECKSUM == '0b94934fbf95230c2acad9bf185ee428b4ec548a6b45f4b0e5fcf7cdb88d9503'


def test_upgrade_from_phase_one_preserves_attendance_and_catalog(admin, catalog, monkeypatch):
    monkeypatch.setenv('COMPAC_ENV', 'test')
    monkeypatch.setenv('COMPAC_ATTENDANCE_MODE', 'demo')
    prefix = '/api/v1/attendance'
    terminal = admin.post(prefix + '/terminals', json={'name': 'Teste legado', 'work_id': catalog['work']['id']}).json()
    authorization = admin.post(prefix + '/test-authorizations', json={'registration': catalog['employee']['registration'], 'terminal_id': terminal['id'], 'acknowledgement': 'TESTE_SUPERVISIONADO'}).json()
    response = admin.post(prefix + '/mark', json={'authorization': authorization['authorization'], 'mark_type': 'ENTRADA'}, headers={'Idempotency-Key': 'migration-once'})
    assert response.status_code == 201
    names = ('employees', 'works', 'materials', 'balances', 'movements', 'attendance_records', 'attendance_authorizations', 'attendance_terminals', 'idempotency_requests', 'audit')
    def snapshot():
        with connect() as db:
            return {name: sorted(json.dumps(dict(r), sort_keys=True) for r in db.execute('SELECT * FROM ' + name)) for name in names}
    before = snapshot()
    previous_revision()
    with connect() as db:
        assert status(db)['applied'] is False
    init_db(allow_migrations=True)
    assert snapshot() == before
    init_db(allow_migrations=True)
    assert snapshot() == before


def test_third_revision_failure_rolls_back_only_its_changes(client_factory):
    previous_revision()
    def failed(db, source=None):
        result = statements(db, source)
        return result + ['INTENTIONALLY INVALID DEVICE MIGRATION'] if source == SQL else result
    with patch('app.migrations.statements', side_effect=failed):
        with pytest.raises((sqlite3.OperationalError, psycopg.ProgrammingError)):
            init_db(allow_migrations=True)
    with connect() as db:
        assert not any(table_exists(db, name) for name in TABLES)
        assert db.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0] == 2
        assert db.execute('SELECT checksum FROM schema_migrations WHERE version=?', (ATTENDANCE_REVISION,)).fetchone()[0] == ATTENDANCE_CHECKSUM


@pytest.mark.parametrize('table', TABLES)
def test_device_table_drift_is_rejected(client_factory, table):
    with connect(write=True) as db:
        for name in TABLES[:TABLES.index(table) + 1]:
            db.execute('DROP TABLE ' + name)
    with pytest.raises(RuntimeError, match='incompleto'):
        init_db()


@pytest.mark.parametrize('index', ('attendance_activation_terminal_expiry','attendance_device_terminal_expiry','attendance_device_authorization_session'))
def test_device_indexes_are_checked(client_factory, index):
    with connect(write=True) as db:
        db.execute('DROP INDEX ' + index)
    with pytest.raises(RuntimeError, match='índices de dispositivo'):
        init_db()
