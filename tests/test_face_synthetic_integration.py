"""Opt-in real-model comparison with entirely generated, fictional identities.

No employee photograph, camera frame or adapter mock is involved. These few
controlled cases verify integration, not a representative FAR/FRR measurement.
"""
import base64
from io import BytesIO
import os
from pathlib import Path

import pytest

pytest.importorskip('cv2')
pytest.importorskip('numpy')
pytest.importorskip('cryptography')
Image = pytest.importorskip('PIL.Image')
ImageEnhance = pytest.importorskip('PIL.ImageEnhance')

from app.attendance.face_engine import FaceError, get_engine
from app.db import connect


FIXTURES = Path(__file__).parent / 'fixtures' / 'faces'
PREFIX = '/api/v1/attendance'


def encoded(raw):
    return base64.b64encode(raw).decode('ascii')


def synthetic(identity):
    return (FIXTURES / f'synthetic-{identity}.jpg').read_bytes()


def variant(raw):
    image = Image.open(BytesIO(raw)).resize((384, 384), Image.Resampling.LANCZOS)
    output = BytesIO()
    ImageEnhance.Brightness(image).enhance(.82).save(output, 'JPEG', quality=85)
    return output.getvalue()


@pytest.fixture
def native_engine(monkeypatch):
    directory = os.getenv('COMPAC_FACE_TEST_MODELS_DIR')
    if not directory:
        pytest.skip('Set COMPAC_FACE_TEST_MODELS_DIR to verify the pinned real models with synthetic portraits.')
    monkeypatch.setenv('COMPAC_FACE_MODELS_DIR', directory)
    monkeypatch.setenv('COMPAC_FACE_THRESHOLD', '.5')
    return get_engine()


@pytest.mark.parametrize('identity', ('a', 'b'))
@pytest.mark.parametrize('changed', (False, True))
def test_real_models_accept_same_synthetic_identity(native_engine, identity, changed):
    raw = synthetic(identity)
    reference = native_engine.prepare_reference(encoded(raw))
    assert native_engine.compare(reference, encoded(variant(raw) if changed else raw)) is True


@pytest.mark.parametrize('reference,candidate', (('a', 'b'), ('b', 'a')))
def test_real_models_reject_distinct_synthetic_identities(native_engine, reference, candidate):
    prepared = native_engine.prepare_reference(encoded(synthetic(reference)))
    assert native_engine.compare(prepared, encoded(synthetic(candidate))) is False


def test_real_detector_rejects_two_synthetic_faces(native_engine):
    left, right = [Image.open(BytesIO(synthetic(identity))) for identity in ('a', 'b')]
    combined = Image.new('RGB', (left.width + right.width, max(left.height, right.height)), 'white')
    combined.paste(left, (0, 0))
    combined.paste(right, (left.width, 0))
    output = BytesIO()
    combined.save(output, 'JPEG', quality=90)
    with pytest.raises(FaceError) as exc:
        native_engine.prepare_reference(encoded(output.getvalue()))
    assert exc.value.code == 'multiple_faces'


def test_real_facial_api_rejects_other_synthetic_identity_then_records_once(native_engine, admin, catalog,
                                                                         client_factory, monkeypatch):
    monkeypatch.setenv('COMPAC_ENV', 'test')
    monkeypatch.setenv('COMPAC_ATTENDANCE_MODE', 'facial')
    monkeypatch.setenv('COMPAC_FACE_SUPERVISED', '1')
    monkeypatch.setenv('COMPAC_FACE_KEY', base64.urlsafe_b64encode(os.urandom(32)).decode('ascii'))
    session = client_factory(base_url='https://testserver')
    session.cookies.update(admin.cookies)
    registration = catalog['employee']['registration']
    reference = session.post(PREFIX + '/face-reference', json={
        'registration': registration, 'image_base64': encoded(synthetic('a')),
        'authorization_basis': 'Fixture inteiramente sintética para validação local de integração, sem pessoa real.',
        'retention_days': 1,
        'acknowledgement': 'AUTORIZACAO_ORGANIZACIONAL_E_BASE_LEGAL_CONFIRMADAS',
    })
    assert reference.status_code == 201, reference.text
    terminal = session.post(PREFIX + '/terminals', json={
        'name': 'Terminal de validação sintética', 'work_id': catalog['work']['id'],
    })
    assert terminal.status_code == 201, terminal.text
    activation = session.post(PREFIX + f'/terminals/{terminal.json()["id"]}/activation')
    assert activation.status_code == 201, activation.text
    device = client_factory(base_url='https://testserver')
    paired = device.post(PREFIX + '/terminal/activate', json={'activation_code': activation.json()['activation_code']})
    assert paired.status_code == 201, paired.text
    assert paired.json()['face_ready'] is True
    def verify(raw):
        return device.post(PREFIX + '/terminal/verify-face', json={
            'registration': registration, 'image_base64': encoded(raw),
            'acknowledgement': 'VERIFICACAO_FACIAL_SUPERVISIONADA',
        })
    rejected = verify(synthetic('b'))
    assert rejected.status_code == 403, rejected.text
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM attendance_face_grants').fetchone()[0] == 0
    verified = verify(variant(synthetic('a')))
    assert verified.status_code == 201, verified.text
    mark_body = {'authorization': verified.json()['authorization'], 'mark_type': 'ENTRADA'}
    for _ in range(2):
        marked = device.post(PREFIX + '/terminal/mark', json=mark_body,
                             headers={'Idempotency-Key': 'synthetic-native-integration-once'})
        assert marked.status_code == 201, marked.text
        assert marked.json()['verification_result'] == 'CORRESPONDENCIA_CONFIRMADA'
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM attendance_facial_records').fetchone()[0] == 1
        record = db.execute('SELECT * FROM attendance_facial_records').fetchone()
        assert record['verification_method'] == 'FACIAL_EXPERIMENTAL'
        assert record['is_test'] == 1
        encrypted = db.execute('SELECT encrypted_image FROM attendance_face_references').fetchone()[0]
        assert encoded(synthetic('a')) not in encrypted
    history = session.get(PREFIX + '/records').json()
    assert history['total'] == 1
    assert history['items'][0]['verification_result'] == 'CORRESPONDENCIA_CONFIRMADA'
