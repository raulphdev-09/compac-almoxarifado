"""Static terminal boundaries, always using disposable application databases."""
import pytest

from conftest import ADMIN_PASSWORD


def test_terminal_shell_is_public_without_exposing_operational_data(client, admin, catalog):
    response = client.get('/ponto-facial')
    assert response.status_code == 200
    assert 'text/html' in response.headers['content-type']
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['permissions-policy'] == 'camera=(self), microphone=(), geolocation=()'
    assert "media-src 'self' blob:" in response.headers['content-security-policy']
    assert catalog['employee']['name'] not in response.text
    assert 'compac_session' not in response.text


def test_administrative_configuration_requires_admin_session(client, admin):
    assert admin.post('/api/auth/logout').status_code == 200
    assert client.get('/ponto-facial/configuracao').status_code == 401
    assert client.post('/api/auth/login', json={'username': 'admin', 'password': ADMIN_PASSWORD}).status_code == 200
    response = client.get('/ponto-facial/configuracao')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert 'Código de ativação' in response.text
    assert ADMIN_PASSWORD not in response.text


@pytest.mark.parametrize('role', ['CONSULTA', 'OPERADOR'])
def test_non_admin_cannot_load_terminal_configuration(admin, client_factory, role):
    assert admin.post('/api/users', json={'name': 'Conta fictícia', 'username': role.lower(), 'password': ADMIN_PASSWORD, 'role': role}).status_code == 201
    session = client_factory()
    assert session.post('/api/auth/login', json={'username': role.lower(), 'password': ADMIN_PASSWORD}).status_code == 200
    assert session.get('/ponto-facial/configuracao').status_code == 403


def test_terminal_assets_do_not_persist_or_upload_camera_frames(client):
    js = client.get('/static/attendance-terminal.js')
    assert js.status_code == 200
    for forbidden in ('localStorage', 'sessionStorage', 'toDataURL', 'toBlob', 'drawImage', 'indexedDB'):
        assert forbidden not in js.text
    assert 'getUserMedia' in js.text
