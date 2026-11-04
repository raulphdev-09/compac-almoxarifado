"""Audit probes using generated SQLite data; prints results and never targets production."""
import json, os, sys, tempfile, inspect, hashlib
if sys.flags.optimize:
    raise RuntimeError('Audit scripts require assertions; run Python without -O')
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for key in ('DATABASE_URL','COMPAC_TEST_DATABASE_URL','COMPAC_REQUIRE_POSTGRES','RENDER','RENDER_EXTERNAL_URL','COMPAC_SETUP_TOKEN','COMPAC_PUBLIC_URL'):
    os.environ.pop(key, None)
os.environ['COMPAC_COOKIE_SECURE']='0'
temp = tempfile.TemporaryDirectory(prefix='compac-security-')
os.environ['COMPAC_DB']=str(Path(temp.name)/'audit.db')
from fastapi.testclient import TestClient
from app.main import app
from app.db import connect
H={'X-Compac-Client':'web'}
PASSWORD='Only-Audit-2026'
result={}
with TestClient(app, headers=H, client=('198.51.100.1', 50000)) as admin:
    result['setup']=admin.post('/api/auth/setup',json={'name':'Fictional audit administrator','username':'audit-admin','password':PASSWORD}).status_code
    result['cookie_flags_local']=admin.cookies.get('compac_session') is not None
    for role in ('OPERADOR','CONSULTA'):
        assert admin.post('/api/users',json={'name':'Fictional '+role,'username':role.lower(),'password':PASSWORD,'role':role}).status_code==201
    with TestClient(app,headers=H,client=('198.51.100.2', 50000)) as anon:
        result['public_openapi']=anon.get('/openapi.json').status_code
        private_paths=['/api/users','/api/schema','/api/catalog/materials','/api/movements','/api/stock','/api/loans','/api/requisitions','/api/tickets','/api/maintenance','/api/alerts','/api/dashboard','/api/audit','/api/export/stock']
        result['unauthenticated_private_gets']={path:anon.get(path).status_code for path in private_paths}
        result['sql_injection_login']=anon.post('/api/auth/login',json={'username':"audit-admin' OR 1=1--",'password':PASSWORD}).status_code
    with TestClient(app,headers=H,client=('198.51.100.3',50000)) as session:
        assert session.post('/api/auth/login',json={'username':'consulta','password':PASSWORD}).status_code==200
        result['readonly_write']=session.post('/api/catalog/categories',json={'name':'Forbidden'}).status_code
        result['readonly_create_admin']=session.post('/api/users',json={'name':'Forbidden','username':'forbidden','password':PASSWORD,'role':'ADMIN'}).status_code
        result['readonly_audit']=session.get('/api/audit').status_code
        result['readonly_users']=session.get('/api/users').status_code
        result['readonly_users_fields']=sorted(session.get('/api/users').json()[0])
        before_token=session.cookies.get('compac_session')
        after=session.post('/api/auth/login',json={'username':'consulta','password':PASSWORD})
        result['session_token_rotates_on_login']=before_token!=session.cookies.get('compac_session')
        cookie=after.headers['set-cookie'].lower()
        result['cookie_flags']={key:key in cookie for key in ('httponly','samesite=strict','max-age=28800')}
        with connect(write=True) as db:
            db.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE token_hash=?",(hashlib.sha256(session.cookies.get('compac_session').encode()).hexdigest(),))
        result['expired_session_rejected']=session.get('/api/auth/me').status_code
    with TestClient(app,headers=H,client=('198.51.100.4',50000)) as bad:
        codes=[bad.post('/api/auth/login',json={'username':'audit-admin','password':'wrong-password'}).status_code for _ in range(11)]
        result['same_origin_11_failures']=codes
    with TestClient(app,headers=H,client=('198.51.100.5',50000)) as brute:
        cycles=[]
        for _ in range(3):
            fails=[brute.post('/api/auth/login',json={'username':'audit-admin','password':'wrong-password'}).status_code for _ in range(9)]
            good=brute.post('/api/auth/login',json={'username':'consulta','password':PASSWORD}).status_code
            cycles.append({'failed_target_attempts':dict(Counter(fails)),'other_account_valid_login':good})
        result['other_account_success_resets_target_protection']=cycles
    distributed=[]
    for index in range(12):
        with TestClient(app,headers=H,client=(f'198.51.100.{index+20}',50000)) as brute:
            distributed.append(brute.post('/api/auth/login',json={'username':'audit-admin','password':'wrong-password'}).status_code)
    result['same_account_12_origins']=distributed
    result['evil_origin']=admin.post('/api/catalog/categories',json={'name':'Origin blocked'},headers={'Origin':'https://evil.invalid'}).status_code
    result['evil_referer_no_origin_custom_header']=admin.post('/api/catalog/categories',json={'name':'Referer policy probe'},headers={'Referer':'https://evil.invalid/payload'}).status_code
    result['missing_custom_header']=admin.post('/api/catalog/categories',json={'name':'Header blocked'},headers={'X-Compac-Client':''}).status_code
    with connect() as db:
        actions=[r['action'] for r in db.execute('SELECT action FROM audit').fetchall()]
        result['failed_login_audit_events']=sum(a in ('LOGIN_FAILED','LOGIN_FALHOU','FALHA_LOGIN') for a in actions)
        encoded=db.execute('SELECT password_hash FROM users LIMIT 1').fetchone()['password_hash']
        result['stored_password_plaintext']=PASSWORD in encoded
        result['scrypt_salt_bytes']=len(bytes.fromhex(encoded.split(':')[0]))
        result['scrypt_digest_bytes']=len(bytes.fromhex(encoded.split(':')[1]))
print(json.dumps(result,ensure_ascii=False,indent=2))
temp.cleanup()
