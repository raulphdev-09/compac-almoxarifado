"""Additive face schema and legacy preservation, using disposable databases only."""
import json
import sqlite3
from unittest.mock import patch

import psycopg
import pytest

from app.db import SCHEMA, connect, init_db
from app.migrations import (
    BASE_CHECKSUM, ATTENDANCE_CHECKSUM, DEVICE_CHECKSUM, DEVICE_REVISION,
    CHECKSUMS, REVISION, SQL, statements, status, table_exists,
)


FACE_TABLES = ('attendance_facial_records', 'attendance_face_grants', 'attendance_face_references')
PREVIOUS_TABLES = tuple(
    item.split('(')[0].split()[-1]
    for item in SCHEMA.split(';') if item.strip().startswith('CREATE TABLE')
) + (
    'idempotency_requests', 'auth_attempts', 'attendance_terminals', 'attendance_authorizations',
    'attendance_records', 'attendance_activation_codes', 'attendance_device_sessions',
    'attendance_device_authorizations',
)
STAMP = '2026-11-05T00:00:00+00:00'


def snapshot():
    with connect() as db:
        return {name: sorted(json.dumps(dict(row), sort_keys=True) for row in db.execute('SELECT * FROM ' + name))
                for name in PREVIOUS_TABLES}


def previous_revision():
    with connect(write=True) as db:
        for table in FACE_TABLES:
            db.execute('DROP TABLE ' + table)
        db.execute('DELETE FROM schema_migrations WHERE version=?', (REVISION,))


def seed_previous(catalog):
    with connect(write=True) as db:
        terminal = db.execute(
            'INSERT INTO attendance_terminals(name,work_id,created_by,created_at) VALUES(?,?,?,?) RETURNING id',
            ('Terminal anterior', catalog['work']['id'], 1, STAMP),
        ).fetchone()['id']
        for token in ('a' * 64, 'b' * 64):
            db.execute('INSERT INTO attendance_authorizations VALUES(?,?,?,?,?,?,?)',
                       (token, catalog['employee']['id'], terminal, 1, STAMP, '2026-11-05T00:01:00+00:00', None))
        db.execute('INSERT INTO attendance_device_sessions VALUES(?,?,?,?,?,?)',
                   ('d' * 64, terminal, 1, STAMP, '2026-11-05T12:00:00+00:00', None))
        db.execute('INSERT INTO attendance_activation_codes VALUES(?,?,?,?,?,?)',
                   ('c' * 64, terminal, 1, STAMP, '2026-11-05T00:10:00+00:00', None))
        db.execute('INSERT INTO attendance_device_authorizations VALUES(?,?)', ('b' * 64, 'd' * 64))
        db.execute(
            'INSERT INTO attendance_records(record_uid,employee_id,work_id,terminal_id,mark_type,marked_at,verification_method,verification_result,is_test,created_by,authorization_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            ('legacy-uid', catalog['employee']['id'], catalog['work']['id'], terminal, 'ENTRADA',
             STAMP, 'DEMO_SUPERVISIONADO', 'SIMULADO', 1, 1, 'a' * 64),
        )
        db.execute('UPDATE attendance_authorizations SET used_at=? WHERE token_hash=?', (STAMP, 'a' * 64))
        db.execute('INSERT INTO idempotency_requests VALUES(?,?,?,?,?,?)',
                   (1, 'POST /terminal/mark:old-device', 'old-key', 'e' * 64, '{"record_uid":"legacy-uid"}', STAMP))
        db.execute('INSERT INTO audit(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)',
                   (1, 'PONTO_TESTE_MARCADO', 'attendance_records', '{"migration_test":true}', STAMP))
    return terminal


def seed_face(catalog):
    terminal = seed_previous(catalog)
    with connect(write=True) as db:
        db.execute('INSERT INTO attendance_face_references VALUES(?,?,?,?,?,?,?)',
                   (catalog['employee']['id'], 'reference-version', 'ciphertext-schema-fixture-not-a-photo',
                    1, 'Autorização fictícia exclusivamente para teste de schema.', STAMP, '2026-12-05T00:00:00+00:00'))
        for token in ('f' * 64, '1' * 64):
            db.execute('INSERT INTO attendance_authorizations VALUES(?,?,?,?,?,?,?)',
                       (token, catalog['employee']['id'], terminal, 1, STAMP, '2026-11-05T00:01:00+00:00', None))
            db.execute('INSERT INTO attendance_face_grants VALUES(?,?,?,?)',
                       (token, 'd' * 64, 'reference-version', 'OPENCV_SFACE_YUNET_V1'))
    return {
        'record_uid': 'face-record-uid', 'employee_id': catalog['employee']['id'],
        'work_id': catalog['work']['id'], 'terminal_id': terminal, 'mark_type': 'ENTRADA',
        'marked_at': STAMP, 'verification_method': 'FACIAL_EXPERIMENTAL',
        'verification_result': 'CORRESPONDENCIA_CONFIRMADA', 'is_test': 1,
        'created_by': 1, 'authorization_hash': 'f' * 64,
    }


def insert_face(db, row):
    db.execute(f"INSERT INTO attendance_facial_records({','.join(row)}) VALUES({','.join('?' for _ in row)})",
               tuple(row.values()))


def test_prior_three_migration_checksums_are_frozen():
    assert BASE_CHECKSUM == 'c3d1fa36db29b2b5bca9daa9a1ee329b94909e1f1d3a53bc248a05bfa5040b20'
    assert ATTENDANCE_CHECKSUM == '0b94934fbf95230c2acad9bf185ee428b4ec548a6b45f4b0e5fcf7cdb88d9503'
    assert DEVICE_CHECKSUM == 'ec8e58f87c95cedd33e3414b4a2bde2c7a3dc1b85b21851078706d1555cb4960'


def test_upgrade_from_devices_preserves_every_previous_row(admin, catalog):
    seed_previous(catalog)
    before = snapshot()
    previous_revision()
    with connect() as db:
        assert status(db)['applied'] is False
    init_db(allow_migrations=True)
    assert snapshot() == before
    init_db(allow_migrations=True)
    assert snapshot() == before
    with connect() as db:
        assert {r['version']: r['checksum'] for r in db.execute('SELECT version,checksum FROM schema_migrations')} == CHECKSUMS
        assert all(table_exists(db, name) for name in FACE_TABLES)
        # A shared employee key must not acquire a generated PostgreSQL identity.
        if db.postgres:
            assert db.execute("SELECT is_identity FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='attendance_face_references' AND column_name='employee_id'").fetchone()[0] == 'NO'


def test_fourth_revision_error_rolls_back_only_new_schema(admin, catalog):
    seed_previous(catalog)
    before = snapshot()
    previous_revision()
    def failed(db, source=None):
        result = statements(db, source)
        return result + ['INTENTIONALLY INVALID FACIAL MIGRATION'] if source == SQL else result
    with patch('app.migrations.statements', side_effect=failed):
        with pytest.raises((sqlite3.OperationalError, psycopg.ProgrammingError)):
            init_db(allow_migrations=True)
    assert snapshot() == before
    with connect() as db:
        assert not any(table_exists(db, table) for table in FACE_TABLES)
        assert db.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0] == 3
        assert db.execute('SELECT checksum FROM schema_migrations WHERE version=?', (DEVICE_REVISION,)).fetchone()[0] == DEVICE_CHECKSUM


def test_production_start_cannot_apply_face_migration(client_factory, monkeypatch):
    previous_revision()
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.setenv('COMPAC_SETUP_TOKEN', 'disposable-face-migration-only')
    with pytest.raises(RuntimeError, match='Migração pendente'):
        init_db()
    with connect() as db:
        assert not any(table_exists(db, table) for table in FACE_TABLES)
        assert db.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0] == 3


@pytest.mark.parametrize('table', FACE_TABLES)
def test_face_table_drift_is_rejected(client_factory, table):
    with connect(write=True) as db:
        for name in FACE_TABLES[:FACE_TABLES.index(table) + 1]:
            db.execute('DROP TABLE ' + name)
    with pytest.raises(RuntimeError, match='incompleto'):
        init_db()


@pytest.mark.parametrize('index', (
    'attendance_facial_records_employee_time', 'attendance_facial_records_work_time', 'attendance_face_grants_session',
))
def test_face_index_drift_is_rejected(client_factory, index):
    with connect(write=True) as db:
        db.execute('DROP INDEX ' + index)
    with pytest.raises(RuntimeError, match='índices de ponto facial'):
        init_db()


@pytest.mark.parametrize('table,field', (
    ('attendance_face_references', 'version_uid'),
    ('attendance_facial_records', 'record_uid'),
    ('attendance_facial_records', 'authorization_hash'),
))
def test_face_uniqueness_drift_is_rejected(client_factory, table, field):
    with connect(write=True) as db:
        definition = next(item for item in statements(db, SQL) if item.startswith('CREATE TABLE IF NOT EXISTS ' + table + '('))
        definition = definition.replace(field + ' TEXT NOT NULL UNIQUE', field + ' TEXT NOT NULL')
        db.execute('DROP TABLE ' + table)
        db.execute(definition)
        for item in statements(db, SQL):
            if item.startswith('CREATE INDEX') and ' ON ' + table + '(' in item:
                db.execute(item)
    with pytest.raises(RuntimeError, match='unicidade'):
        init_db()


@pytest.mark.parametrize('field,value', (
    ('mark_type', 'INVALID'), ('verification_method', 'DEMO_SUPERVISIONADO'),
    ('verification_result', 'SIMULADO'), ('is_test', 0), ('employee_id', 999999999),
    ('authorization_hash', 'x' * 64),
))
def test_face_schema_rejects_forged_or_misclassified_marks(admin, catalog, field, value):
    row = seed_face(catalog)
    with pytest.raises((sqlite3.IntegrityError, psycopg.IntegrityError)):
        with connect(write=True) as db:
            insert_face(db, {**row, field: value})
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM attendance_facial_records').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM attendance_records').fetchone()[0] == 1


@pytest.mark.parametrize('field', ('record_uid', 'authorization_hash'))
def test_facial_uid_and_grant_cannot_be_reused(admin, catalog, field):
    row = seed_face(catalog)
    with connect(write=True) as db:
        insert_face(db, row)
    duplicate = {**row, 'record_uid': 'another-facial-record', 'authorization_hash': '1' * 64}
    duplicate[field] = row[field]
    with pytest.raises((sqlite3.IntegrityError, psycopg.IntegrityError)):
        with connect(write=True) as db:
            insert_face(db, duplicate)
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM attendance_facial_records').fetchone()[0] == 1


def test_face_grant_requires_real_schema_algorithm_and_valid_session(admin, catalog):
    seed_face(catalog)
    for field, value in (('algorithm', 'AUTO_APPROVE'), ('device_session_hash', 'missing-session')):
        with pytest.raises((sqlite3.IntegrityError, psycopg.IntegrityError)):
            with connect(write=True) as db:
                db.execute(f'UPDATE attendance_face_grants SET {field}=? WHERE token_hash=?', (value, 'f' * 64))


def test_reference_employee_key_is_unique_and_foreign_key_protected(admin, catalog):
    seed_face(catalog)
    for employee, version in ((catalog['employee']['id'], 'different-version'), (999999999, 'nonexistent-employee')):
        with pytest.raises((sqlite3.IntegrityError, psycopg.IntegrityError)):
            with connect(write=True) as db:
                db.execute('INSERT INTO attendance_face_references VALUES(?,?,?,?,?,?,?)',
                           (employee, version, 'schema-test-ciphertext', 1, 'Fictitious test authorization.', STAMP, '2026-12-05T00:00:00+00:00'))
