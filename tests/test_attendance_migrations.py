"""Attendance schema evolution, always inside disposable fixture databases."""
import hashlib
import json
import sqlite3
from unittest.mock import patch

import psycopg
import pytest

from app.db import SCHEMA, connect, init_db
from app.migrations import (
    BASE_CHECKSUM, BASE_REVISION, BASE_SQL, CHECKSUM, REVISION, CHECKSUMS, ATTENDANCE_SQL,
    migrate, statements, status, table_exists,
)


NEW_TABLES = ('attendance_device_authorizations', 'attendance_device_sessions', 'attendance_activation_codes',
              'attendance_records', 'attendance_authorizations', 'attendance_terminals')
LEGACY_TABLES = tuple(
    statement.split('(')[0].split()[-1]
    for statement in SCHEMA.split(';') if statement.strip().startswith('CREATE TABLE')
) + ('idempotency_requests', 'auth_attempts')


def snapshot():
    with connect() as db:
        return {
            name: sorted(json.dumps(dict(row), sort_keys=True) for row in db.execute(f'SELECT * FROM {name}'))
            for name in LEGACY_TABLES
        }


def to_security_revision():
    """Recreate only the prior schema revision, never a real database."""
    with connect(write=True) as db:
        for name in NEW_TABLES:
            db.execute(f'DROP TABLE {name}')
        db.execute('DELETE FROM schema_migrations WHERE version<>?', (BASE_REVISION,))


def seed_security_rows():
    with connect(write=True) as db:
        db.execute(
            'INSERT INTO idempotency_requests VALUES(?,?,?,?,?,?)',
            (1, 'migration-test', 'original-key', 'f' * 64, '{"id":1}', '2026-11-05T00:00:00+00:00'),
        )
        db.execute(
            'INSERT INTO auth_attempts(account_hash,origin_hash,attempted_at) VALUES(?,?,?)',
            ('a' * 64, 'b' * 64, 1),
        )


def test_first_revision_literal_checksum_is_unchanged():
    # Freeze the checksum from the completed security phase, not its alias.
    assert BASE_REVISION == '001_security_integrity'
    assert BASE_CHECKSUM == 'c3d1fa36db29b2b5bca9daa9a1ee329b94909e1f1d3a53bc248a05bfa5040b20'
    assert hashlib.sha256(BASE_SQL.encode()).hexdigest() == BASE_CHECKSUM


def test_upgrade_from_security_preserves_all_legacy_rows(admin, catalog):
    seed_security_rows()
    before = snapshot()
    to_security_revision()
    with connect() as db:
        assert status(db) == {'revision': REVISION, 'applied': False, 'checksum_valid': None}
    init_db(allow_migrations=True)
    assert snapshot() == before
    init_db(allow_migrations=True)
    assert snapshot() == before
    with connect() as db:
        versions = {r['version']: r['checksum'] for r in db.execute('SELECT version,checksum FROM schema_migrations')}
        assert versions == CHECKSUMS
        assert all(table_exists(db, name) for name in NEW_TABLES)
        assert not table_exists(db, 'attendance_employees')


def test_upgrade_is_not_applied_by_production_start(client_factory, monkeypatch):
    to_security_revision()
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.setenv('COMPAC_SETUP_TOKEN', 'disposable-migration-test')
    with pytest.raises(RuntimeError, match='Migração pendente'):
        init_db()
    with connect() as db:
        assert not any(table_exists(db, name) for name in NEW_TABLES)
        assert db.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0] == 1


def test_failed_second_revision_rolls_back_only_new_changes(admin, catalog):
    seed_security_rows()
    to_security_revision()
    before = snapshot()

    def fail_attendance(db, source=None):
        result = statements(db, source)
        return result + ['INTENTIONALLY INVALID MIGRATION SQL'] if source != BASE_SQL else result

    with patch('app.migrations.statements', side_effect=fail_attendance):
        with pytest.raises((sqlite3.OperationalError, psycopg.ProgrammingError)):
            init_db(allow_migrations=True)
    assert snapshot() == before
    with connect() as db:
        assert not any(table_exists(db, name) for name in NEW_TABLES)
        versions = [r['version'] for r in db.execute('SELECT version FROM schema_migrations')]
        assert versions == [BASE_REVISION]


def test_old_checksum_tampering_is_detected_even_with_latest_applied(client_factory):
    with connect(write=True) as db:
        db.execute('UPDATE schema_migrations SET checksum=? WHERE version=?', ('wrong-old-checksum', BASE_REVISION))
    with connect() as db:
        assert status(db)['checksum_valid'] is False
    with pytest.raises(RuntimeError, match='Checksum'):
        init_db()


def test_unknown_revision_fails_closed(client_factory):
    with connect(write=True) as db:
        db.execute('INSERT INTO schema_migrations VALUES(?,?,?)', ('999_unknown', 'checksum', '2026-11-05'))
    with pytest.raises(RuntimeError, match='desconhecida'):
        init_db()


def test_revision_gap_fails_closed(client_factory):
    with connect(write=True) as db:
        db.execute('DELETE FROM schema_migrations WHERE version=?', (BASE_REVISION,))
    with pytest.raises(RuntimeError, match='Sequência'):
        init_db()


@pytest.mark.parametrize('table', NEW_TABLES)
def test_latest_revision_requires_each_attendance_table(client_factory, table):
    # Test a missing dependency without leaving foreign keys to that table.
    with connect(write=True) as db:
        for name in NEW_TABLES[:NEW_TABLES.index(table) + 1]:
            db.execute(f'DROP TABLE {name}')
    with pytest.raises(RuntimeError, match='incompleto'):
        init_db()


@pytest.mark.parametrize('index', (
    'attendance_records_employee_time', 'attendance_records_work_time', 'attendance_authorizations_expiry',
))
def test_latest_revision_requires_attendance_indexes(client_factory, index):
    with connect(write=True) as db:
        db.execute(f'DROP INDEX {index}')
    with pytest.raises(RuntimeError, match='índices de ponto'):
        init_db()


@pytest.mark.parametrize('field', ('record_uid', 'authorization_hash'))
def test_latest_revision_requires_replay_uniqueness(client_factory, field):
    with connect(write=True) as db:
        definition = next(item for item in statements(db, ATTENDANCE_SQL) if item.startswith('CREATE TABLE IF NOT EXISTS attendance_records'))
        definition = definition.replace(f'{field} TEXT NOT NULL UNIQUE', f'{field} TEXT NOT NULL')
        db.execute('DROP TABLE attendance_records')
        db.execute(definition)
        for statement in statements(db, ATTENDANCE_SQL):
            if statement.startswith('CREATE INDEX') and ' ON attendance_records(' in statement:
                db.execute(statement)
    with pytest.raises(RuntimeError, match='unicidade'):
        init_db()


def attendance_row(catalog):
    with connect(write=True) as db:
        terminal = db.execute(
            'INSERT INTO attendance_terminals(name,work_id,created_by,created_at) VALUES(?,?,?,?) RETURNING id',
            ('Terminal fictício', catalog['work']['id'], 1, '2026-11-05T00:00:00+00:00'),
        ).fetchone()['id']
        db.execute(
            'INSERT INTO attendance_authorizations(token_hash,employee_id,terminal_id,created_by,created_at,expires_at) VALUES(?,?,?,?,?,?)',
            ('a' * 64, catalog['employee']['id'], terminal, 1, '2026-11-05T00:00:00+00:00', '2026-11-05T00:01:00+00:00'),
        )
    return {
        'record_uid': 'test-record', 'employee_id': catalog['employee']['id'],
        'work_id': catalog['work']['id'], 'terminal_id': terminal, 'mark_type': 'ENTRADA',
        'marked_at': '2026-11-05T00:00:30+00:00', 'verification_method': 'DEMO_SUPERVISIONADO',
        'verification_result': 'SIMULADO', 'is_test': 1, 'created_by': 1, 'authorization_hash': 'a' * 64,
    }


def insert_record(db, row):
    columns = tuple(row)
    db.execute(
        f"INSERT INTO attendance_records({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
        tuple(row.values()),
    )


@pytest.mark.parametrize('field,value', (
    ('mark_type', 'INVALID'), ('verification_method', 'FACE_REAL'),
    ('verification_result', 'APROVADO'), ('is_test', 0), ('employee_id', 99999999),
))
def test_schema_rejects_non_demo_and_invalid_records(admin, catalog, field, value):
    row = attendance_row(catalog)
    with pytest.raises((sqlite3.IntegrityError, psycopg.IntegrityError)):
        with connect(write=True) as db:
            insert_record(db, {**row, field: value})
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM attendance_records').fetchone()[0] == 0


@pytest.mark.parametrize('field', ('record_uid', 'authorization_hash'))
def test_duplicate_uid_or_authorization_cannot_create_second_record(admin, catalog, field):
    row = attendance_row(catalog)
    with connect(write=True) as db:
        insert_record(db, row)
        # A distinct valid authorization lets the UID constraint be exercised independently.
        db.execute(
            'INSERT INTO attendance_authorizations(token_hash,employee_id,terminal_id,created_by,created_at,expires_at) VALUES(?,?,?,?,?,?)',
            ('b' * 64, row['employee_id'], row['terminal_id'], 1, row['marked_at'], '2026-11-05T00:02:00+00:00'),
        )
    duplicate = {**row, 'record_uid': 'another-record', 'authorization_hash': 'b' * 64}
    duplicate[field] = row[field]
    with pytest.raises((sqlite3.IntegrityError, psycopg.IntegrityError)):
        with connect(write=True) as db:
            insert_record(db, duplicate)
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM attendance_records').fetchone()[0] == 1
