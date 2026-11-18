"""Compatibility release: material opening receipts and explicit consumption."""
import uuid

import pytest

from app.db import connect


def body(catalog, amount):
    return {'code': 'OPEN-' + uuid.uuid4().hex[:8], 'description': 'Opening stock fixture',
            'category_id': catalog['category']['id'], 'unit': 'UN', 'minimum_stock': '0',
            'individualizable': False, 'status': 'ATIVO',
            'initial_stock': {'quantity': amount, 'location_id': catalog['origin']['id'],
                              'source_type': 'NOTA_FISCAL', 'source_reference': 'NF-SYNTHETIC'}}


@pytest.mark.parametrize('amount', ['0', '5.125'])
def test_material_opening_stock_is_atomic_traceable_and_replayable(admin, catalog, amount):
    payload = body(catalog, amount)
    headers = {'Idempotency-Key': uuid.uuid4().hex}
    first = admin.post('/api/catalog/materials', json=payload, headers=headers)
    replay = admin.post('/api/catalog/materials', json=payload, headers=headers)
    assert first.status_code == replay.status_code == 201, (first.text, replay.text)
    assert first.json() == replay.json()
    with connect() as db:
        rows = db.execute('SELECT * FROM movements WHERE material_id=?', (first.json()['id'],)).fetchall()
        if amount == '0':
            assert not rows
            assert not db.execute('SELECT * FROM balances WHERE material_id=?', (first.json()['id'],)).fetchall()
        else:
            assert len(rows) == 1
            assert rows[0]['quantity'] == 5125
            assert db.execute('SELECT quantity FROM balances WHERE material_id=?', (first.json()['id'],)).fetchone()['quantity'] == 5125
    if amount != '0':
        movement = next(row for row in admin.get('/api/movements').json() if row['material_id'] == first.json()['id'])
        assert movement['source_reference'] == 'NF-SYNTHETIC'


def test_negative_opening_stock_or_missing_reference_has_no_partial_material(admin, catalog):
    for amount, reference in [('-1', 'NF'), ('2', '')]:
        payload = body(catalog, amount)
        payload['initial_stock']['source_reference'] = reference
        response = admin.post('/api/catalog/materials', json=payload, headers={'Idempotency-Key': uuid.uuid4().hex})
        assert response.status_code == 422, response.text
        with connect() as db:
            assert not db.execute('SELECT id FROM materials WHERE code=?', (payload['code'],)).fetchone()


def test_receipt_failure_rolls_back_material_balance_and_audit(admin, catalog, monkeypatch):
    from app import main
    payload = body(catalog, '3')
    def fail_receipt(*args, **kwargs):
        from fastapi import HTTPException
        raise HTTPException(409, 'Synthetic receipt failure')
    monkeypatch.setattr(main, 'perform_movement', fail_receipt)
    response = admin.post('/api/catalog/materials', json=payload, headers={'Idempotency-Key': uuid.uuid4().hex})
    assert response.status_code == 409
    with connect() as db:
        assert not db.execute('SELECT id FROM materials WHERE code=?', (payload['code'],)).fetchone()


def test_explicit_consumption_keeps_responsible_without_creating_loan(admin, catalog):
    payload = body(catalog, '8')
    response = admin.post('/api/catalog/materials', json=payload, headers={'Idempotency-Key': uuid.uuid4().hex})
    identifier = response.json()['id']
    movement = admin.post('/api/movements', json={
        'type': 'SAIDA', 'purpose': 'CONSUMO', 'material_id': identifier, 'quantity': '2',
        'origin_id': catalog['origin']['id'], 'employee_id': catalog['employee']['id'],
    }, headers={'Idempotency-Key': uuid.uuid4().hex})
    assert movement.status_code == 201, movement.text
    with connect() as db:
        assert not db.execute('SELECT * FROM loans WHERE material_id=?', (identifier,)).fetchall()
    saved = next(row for row in admin.get('/api/movements').json() if row['id'] == movement.json()['id'])
    assert saved['purpose'] == 'CONSUMO'
    assert saved['employee_id'] == catalog['employee']['id']


def test_editing_material_cannot_change_quantity(admin, catalog):
    payload = body(catalog, '1')
    row = admin.post('/api/catalog/materials', json=payload, headers={'Idempotency-Key': uuid.uuid4().hex}).json()
    payload.pop('initial_stock')
    response = admin.put('/api/catalog/materials/' + str(row['id']), json={**payload, 'quantity': '900'})
    assert response.status_code == 422
    with connect() as db:
        assert db.execute('SELECT quantity FROM balances WHERE material_id=?', (row['id'],)).fetchone()['quantity'] == 1000
