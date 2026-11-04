import ssl

import pytest

from app.db import postgres_options


def test_remote_postgres_always_verifies_tls():
    settings = postgres_options(
        'postgresql://example:example@db.example.invalid/compac?sslmode=disable&channel_binding=require'
    )
    assert settings['sslmode'] == 'verify-full'
    trust = ssl.create_default_context(cafile=settings['sslrootcert'])
    assert trust.get_ca_certs(), 'External PostgreSQL needs a usable CA bundle'
    assert settings['channel_binding'] == 'require'


def test_database_url_must_be_postgres():
    with pytest.raises(RuntimeError, match='PostgreSQL'):
        postgres_options('sqlite:///temporary.db')


def test_free_hosting_refuses_temporary_database(client_factory):
    with pytest.raises(RuntimeError, match='DATABASE_URL'):
        client_factory(environment={'COMPAC_REQUIRE_POSTGRES': '1', 'DATABASE_URL': None})


def test_case_insensitive_registration_is_unique(admin, catalog):
    original = catalog['category']
    response = admin.post('/api/catalog/categories', json={'name': original['name'].swapcase()})
    assert response.status_code == 409


def test_login_preserves_case_insensitive_usernames(admin):
    assert admin.post('/api/auth/logout').status_code == 200
    response = admin.post('/api/auth/login', json={
        'username': 'ADMIN', 'password': 'Admin-Seguro-2026',
    })
    assert response.status_code == 200
    assert response.json()['username'] == 'admin'


def test_large_quantities_and_restart_persistence(admin, catalog, client_factory):
    material = catalog['material']['id']
    # More than 2^31 milliunits proves PostgreSQL uses 64-bit quantities.
    amount = 3_000_000.125
    response = admin.post('/api/movements', headers={'Idempotency-Key': 'large-quantity-once'}, json={
        'type': 'ENTRADA', 'material_id': material, 'quantity': amount,
        'destination_id': catalog['origin']['id'],
    })
    assert response.status_code == 201
    restarted = client_factory()
    restarted.cookies.update(admin.cookies)
    stock = restarted.get('/api/stock')
    assert stock.status_code == 200
    assert next(row['quantity'] for row in stock.json() if row['material_id'] == material) == amount
