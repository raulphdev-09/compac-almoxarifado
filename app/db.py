import os
import re
import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import certifi
import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT NOT NULL UNIQUE COLLATE NOCASE,name TEXT NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS works(id INTEGER PRIMARY KEY,code TEXT NOT NULL UNIQUE COLLATE NOCASE,name TEXT NOT NULL,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE COLLATE NOCASE,description TEXT);
CREATE TABLE IF NOT EXISTS locations(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE COLLATE NOCASE,work_id INTEGER REFERENCES works(id));
CREATE TABLE IF NOT EXISTS employees(id INTEGER PRIMARY KEY,registration TEXT NOT NULL UNIQUE COLLATE NOCASE,name TEXT NOT NULL,job_title TEXT NOT NULL,work_id INTEGER REFERENCES works(id),status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS materials(id INTEGER PRIMARY KEY,code TEXT NOT NULL UNIQUE COLLATE NOCASE,description TEXT NOT NULL,category_id INTEGER NOT NULL REFERENCES categories(id),unit TEXT NOT NULL,minimum_stock REAL NOT NULL DEFAULT 0,individualizable INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS equipment(id INTEGER PRIMARY KEY,asset_tag TEXT NOT NULL UNIQUE COLLATE NOCASE,material_id INTEGER NOT NULL REFERENCES materials(id),location_id INTEGER NOT NULL REFERENCES locations(id),condition TEXT NOT NULL,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS balances(material_id INTEGER NOT NULL REFERENCES materials(id),location_id INTEGER NOT NULL REFERENCES locations(id),quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity>=0),PRIMARY KEY(material_id,location_id));
CREATE TABLE IF NOT EXISTS requisitions(id INTEGER PRIMARY KEY,work_id INTEGER NOT NULL REFERENCES works(id),requester_id INTEGER NOT NULL REFERENCES users(id),priority TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'PENDENTE',notes TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requisition_items(id INTEGER PRIMARY KEY,requisition_id INTEGER NOT NULL REFERENCES requisitions(id),material_id INTEGER NOT NULL REFERENCES materials(id),quantity INTEGER NOT NULL CHECK(quantity>0));
CREATE TABLE IF NOT EXISTS movements(id INTEGER PRIMARY KEY,type TEXT NOT NULL,material_id INTEGER NOT NULL REFERENCES materials(id),quantity INTEGER NOT NULL,origin_id INTEGER REFERENCES locations(id),destination_id INTEGER REFERENCES locations(id),employee_id INTEGER REFERENCES employees(id),notes TEXT NOT NULL DEFAULT '',user_id INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,requisition_id INTEGER REFERENCES requisitions(id));
CREATE TABLE IF NOT EXISTS loans(id INTEGER PRIMARY KEY,employee_id INTEGER NOT NULL REFERENCES employees(id),material_id INTEGER NOT NULL REFERENCES materials(id),location_id INTEGER NOT NULL REFERENCES locations(id),quantity INTEGER NOT NULL CHECK(quantity>=0),due_date TEXT,movement_id INTEGER NOT NULL REFERENCES movements(id),created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL,priority TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'ABERTO',work_id INTEGER REFERENCES works(id),assignee_id INTEGER REFERENCES users(id),creator_id INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ticket_comments(id INTEGER PRIMARY KEY,ticket_id INTEGER NOT NULL REFERENCES tickets(id),user_id INTEGER NOT NULL REFERENCES users(id),body TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY,supplier TEXT NOT NULL,document_number TEXT,purchase_date TEXT NOT NULL,material_id INTEGER NOT NULL REFERENCES materials(id),work_id INTEGER REFERENCES works(id),quantity REAL NOT NULL CHECK(quantity>0),unit_cost REAL NOT NULL CHECK(unit_cost>=0),total_cost REAL NOT NULL CHECK(total_cost>=0));
CREATE TABLE IF NOT EXISTS consumption_profiles(id INTEGER PRIMARY KEY,work_id INTEGER NOT NULL REFERENCES works(id),activity TEXT NOT NULL,material_id INTEGER NOT NULL REFERENCES materials(id),consumption_per_unit REAL NOT NULL CHECK(consumption_per_unit>0),team TEXT,shift TEXT);
CREATE TABLE IF NOT EXISTS production(id INTEGER PRIMARY KEY,work_id INTEGER NOT NULL REFERENCES works(id),activity TEXT NOT NULL,quantity_produced REAL NOT NULL CHECK(quantity_produced>0),produced_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS maintenance(id INTEGER PRIMARY KEY,equipment_id INTEGER NOT NULL REFERENCES equipment(id),defect TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'ABERTA',resolution TEXT,created_at TEXT NOT NULL,closed_at TEXT,user_id INTEGER NOT NULL REFERENCES users(id));
CREATE UNIQUE INDEX IF NOT EXISTS open_maintenance ON maintenance(equipment_id) WHERE status='ABERTA';
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),action TEXT NOT NULL,entity TEXT NOT NULL,record_id INTEGER,details TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS movement_date ON movements(created_at);
CREATE INDEX IF NOT EXISTS ticket_status ON tickets(status);
'''

# SQLite is retained for local development. PostgreSQL provides durable storage
# independently of the web service's ephemeral filesystem on Render Free.
CASE_INSENSITIVE_KEYS = {
    'users': 'username', 'works': 'code', 'categories': 'name',
    'locations': 'name', 'employees': 'registration',
    'materials': 'code', 'equipment': 'asset_tag',
}
POSTGRES_SCHEMA = SCHEMA.replace(' COLLATE NOCASE', '')
POSTGRES_SCHEMA = POSTGRES_SCHEMA.replace(
    'id INTEGER PRIMARY KEY', 'id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY',
)
POSTGRES_SCHEMA = re.sub(r'\bINTEGER\b', 'BIGINT', POSTGRES_SCHEMA)
POSTGRES_SCHEMA = re.sub(r'\bREAL\b', 'NUMERIC', POSTGRES_SCHEMA)
for table, column in CASE_INSENSITIVE_KEYS.items():
    POSTGRES_SCHEMA += (
        f'CREATE UNIQUE INDEX IF NOT EXISTS uq_{table}_{column}_lower '
        f'ON {table}(LOWER({column}));\n'
    )


class Record(dict):
    """Preserve the mapping and positional access used by the existing queries."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def record(row):
    if row is None:
        return None
    return Record({key: float(value) if isinstance(value, Decimal) else value
                   for key, value in dict(row).items()})


class Result:
    def __init__(self, cursor):
        self.cursor = cursor

    def fetchone(self):
        return record(self.cursor.fetchone())

    def fetchall(self):
        return [record(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        return (record(row) for row in self.cursor)


class Database:
    def __init__(self, connection, postgres=False):
        self.connection = connection
        self.postgres = postgres

    def execute(self, sql, params=()):
        # All queries are controlled by the application. Values stay bound
        # parameters; no values are interpolated into the SQL text.
        if self.postgres:
            sql = sql.replace('?', '%s')
        return Result(self.connection.execute(sql, params))

    def executemany(self, sql, params):
        if self.postgres:
            cursor = self.connection.cursor()
            cursor.executemany(sql.replace('?', '%s'), params)
        else:
            cursor = self.connection.executemany(sql, params)
        return Result(cursor)

    def executescript(self, sql):
        if self.postgres:
            # The schema contains only ordinary DDL; no procedural blocks.
            for statement in sql.split(';'):
                if statement.strip():
                    self.connection.execute(statement)
        else:
            self.connection.executescript(sql)


def postgres_options(url):
    if not url.startswith(('postgresql://', 'postgres://')):
        raise RuntimeError('DATABASE_URL deve ser uma conexão PostgreSQL válida.')
    options = conninfo_to_dict(url)
    host = options.get('host', '')
    if host not in ('localhost', '127.0.0.1', '::1'):
        # Verify the chain and hostname using an explicit CA bundle: the OpenSSL
        # bundled with psycopg-binary may not find Render's system certificates.
        options['sslmode'] = 'verify-full'
        options.setdefault('sslrootcert', certifi.where())
    options.setdefault('connect_timeout', '10')
    return options


@contextmanager
def connect(write=False):
    url = os.getenv('DATABASE_URL', '').strip()
    if url:
        # Keep transaction-pooling connections compatible without relying on
        # named prepared statements retained by an external pooler.
        connection = psycopg.connect(**postgres_options(url), row_factory=dict_row, prepare_threshold=None)
        db = Database(connection, postgres=True)
    else:
        if os.getenv('COMPAC_REQUIRE_POSTGRES') == '1':
            raise RuntimeError('Configure DATABASE_URL para preservar os dados na hospedagem gratuita.')
        path = os.getenv('COMPAC_DB', str(Path(__file__).resolve().parents[1] / '.data' / 'compac.db'))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=20)
        connection.row_factory = sqlite3.Row
        db = Database(connection)
    try:
        if db.postgres and write:
            # Preserve the serialized-writer semantics of the original SQLite
            # workflow, including bootstrap and multi-item fulfillment.
            connection.execute("SET LOCAL lock_timeout = '15s'")
            connection.execute("SET LOCAL statement_timeout = '20s'")
            connection.execute('SELECT pg_advisory_xact_lock(1129270608)')
        elif not db.postgres:
            connection.execute('PRAGMA foreign_keys=ON')
            if write:
                connection.execute('BEGIN IMMEDIATE')
        yield db
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def init_db(*, allow_migrations=None):
    from .migrations import migrate

    if os.getenv('RENDER') == 'true' and not os.getenv('COMPAC_SETUP_TOKEN'):
        raise RuntimeError('Configure COMPAC_SETUP_TOKEN antes de publicar o serviço.')
    if allow_migrations is None:
        # Production upgrades require the explicit CLI, after backup/approval.
        url = os.getenv('DATABASE_URL', '').strip()
        local = not url or postgres_options(url).get('host') in ('localhost', '127.0.0.1', '::1')
        allow_migrations = os.getenv('RENDER') != 'true' and local
    if not os.getenv('DATABASE_URL', '').strip():
        with connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
    with connect(write=True) as db:
        if allow_migrations:
            schema = POSTGRES_SCHEMA if db.postgres else SCHEMA
            for statement in schema.split(';'):
                if statement.strip():
                    db.execute(statement)
        migrate(db, allow_apply=allow_migrations)
