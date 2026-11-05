"""Run phase-1 attendance against disposable fictional data, without a camera."""
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    with tempfile.TemporaryDirectory(prefix='compac-ponto-demo-') as directory:
        environment = dict(os.environ)
        for name in ('DATABASE_URL', 'COMPAC_TEST_DATABASE_URL', 'RENDER_EXTERNAL_URL', 'COMPAC_PUBLIC_URL', 'COMPAC_SETUP_TOKEN'):
            environment.pop(name, None)
        environment.update(COMPAC_DB=str(Path(directory) / 'demo.db'), COMPAC_REQUIRE_POSTGRES='', RENDER='',
                           COMPAC_ENV='test', COMPAC_ATTENDANCE_MODE='demo', COMPAC_COOKIE_SECURE='0')
        with patch.dict(os.environ, environment, clear=True):
            from app.main import app
            with TestClient(app, headers={'X-Compac-Client': 'web'}) as client:
                def post(path, payload, key=None):
                    response = client.post(path, json=payload, headers={'Idempotency-Key': key or str(uuid.uuid4())})
                    if response.status_code not in (200, 201):
                        raise RuntimeError(f'Falha na demonstração local: HTTP {response.status_code}')
                    return response.json()
                post('/api/auth/setup', {'name': 'Administrador fictício', 'username': 'demo', 'password': uuid.uuid4().hex})
                work = post('/api/catalog/works', {'code': 'DEMO', 'name': 'Obra fictícia', 'status': 'ATIVA'})
                post('/api/catalog/employees', {'registration': 'DEMO-001', 'name': 'Pessoa fictícia', 'job_title': 'Teste', 'work_id': work['id'], 'status': 'ATIVO'})
                terminal = post('/api/v1/attendance/terminals', {'name': 'Terminal fictício', 'work_id': work['id']})
                marks = []
                for kind in ('ENTRADA', 'INICIO_INTERVALO', 'RETORNO_INTERVALO', 'SAIDA'):
                    authorization = post('/api/v1/attendance/test-authorizations', {'registration': 'DEMO-001', 'terminal_id': terminal['id'], 'acknowledgement': 'TESTE_SUPERVISIONADO'})
                    payload = {'authorization': authorization['authorization'], 'mark_type': kind}
                    key = str(uuid.uuid4())
                    result = post('/api/v1/attendance/mark', payload, key)
                    if post('/api/v1/attendance/mark', payload, key)['id'] != result['id']:
                        raise RuntimeError('Falha na proteção de reenvio.')
                    marks.append({field: result[field] for field in ('record_uid', 'mark_type', 'marked_at', 'verification_result', 'is_test')})
                print(json.dumps({'experimental': True, 'facial_recognition': False, 'records': marks}, ensure_ascii=False, indent=2))
    print('Demonstração encerrada; banco temporário removido. Nenhuma foto ou dado real utilizado.')


if __name__ == '__main__':
    main()
