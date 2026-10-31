import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

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

@contextmanager
def connect(write=False):
    path = os.getenv('COMPAC_DB', str(Path(__file__).resolve().parents[1] / '.data' / 'compac.db'))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        if write:
            db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init_db():
    if os.getenv('RENDER') == 'true' and not os.getenv('COMPAC_SETUP_TOKEN'):
        raise RuntimeError('Configure COMPAC_SETUP_TOKEN antes de publicar o serviço.')
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript(SCHEMA)
