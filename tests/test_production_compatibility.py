"""The document release starts on the deployed ledger without running DDL."""
from app.db import Database
from app.migrations import REVISION


def test_documents_release_starts_read_only_against_existing_schema(admin, monkeypatch, client_factory):
    assert REVISION == '004_attendance_face'
    execute = Database.execute

    def reject_schema_or_business_writes(self, sql, params=()):
        first = sql.lstrip().split(None, 1)[0].upper()
        assert first not in {'CREATE', 'ALTER', 'DROP', 'INSERT', 'UPDATE', 'DELETE'}, sql
        return execute(self, sql, params)

    monkeypatch.setattr(Database, 'execute', reject_schema_or_business_writes)
    client = client_factory(environment={
        'RENDER': 'true', 'COMPAC_SETUP_TOKEN': 'synthetic-test-only',
        'COMPAC_ENV': 'production', 'COMPAC_ATTENDANCE_MODE': 'disabled', 'COMPAC_FACE_SUPERVISED': '0',
    })
    assert client.get('/health').status_code == 200
    assert client.get('/api/v1/attendance/terminal/status').status_code == 404
    assert client.get('/api/reports/stock/export?format=pdf').status_code == 401
    assert client.get('/api/import/materials/template').status_code == 401
