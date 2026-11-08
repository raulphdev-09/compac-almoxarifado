"""Image/crypto/adapter tests; no real employee photographs or identities.

The detector/recognizer doubles below are test-only. Actual-model tests reject
geometric images; they never pretend that a mock validates biometric accuracy.
"""
import base64
import hashlib
import io
import os
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

np = pytest.importorskip('numpy')
Image = pytest.importorskip('PIL.Image')
pytest.importorskip('cv2')
pytest.importorskip('cryptography')

from app.attendance import face_engine as module
from app.attendance.face_engine import FaceEngine, FaceError


def picture(size=(160, 160), format='PNG', **options):
    # Deliberately geometric, not a portrait or a real/synthetic person's face.
    image = Image.new('RGB', size, color=(100, 150, 200))
    out = io.BytesIO()
    image.save(out, format, **options)
    return out.getvalue()


def encoded(raw=None, **options):
    return base64.b64encode(raw if raw is not None else picture(**options)).decode('ascii')


def assert_error(code, operation, status=None):
    with pytest.raises(FaceError) as error:
        operation()
    assert error.value.code == code
    assert len(str(error.value)) < 180
    if status is not None:
        assert error.value.status_code == status
    return error.value


@pytest.fixture
def cipher_key(monkeypatch):
    monkeypatch.setenv('COMPAC_FACE_KEY', base64.urlsafe_b64encode(os.urandom(32)).decode('ascii'))


@pytest.fixture
def adapter():
    # Injection exists solely in tests; no demo provider is shipped at runtime.
    engine = FaceEngine.__new__(FaceEngine)
    engine.np = np
    engine.cv = SimpleNamespace(FaceRecognizerSF_FR_COSINE=0)
    engine.threshold = .5
    engine._lock = Lock()
    face = np.array([[20, 20, 100, 100, 45, 50, 90, 50, 68, 70, 48, 95, 88, 95, .99]], dtype=np.float32)
    engine.detector = Mock()
    engine.detector.detect.return_value = (1, face)
    engine.recognizer = Mock()
    engine.recognizer.alignCrop.return_value = np.zeros((112, 112, 3), dtype=np.uint8)
    engine.recognizer.feature.return_value = np.ones((1, 128), dtype=np.float32)
    engine.recognizer.match.return_value = .75
    return engine


@pytest.mark.parametrize('value', ['', '%%%%', 'data:image/png;base64,AAAA', 'a' * (module.MAX_BASE64_LENGTH + 1), None])
def test_base64_is_bounded_and_strict(value):
    assert_error('invalid_image', lambda: module._decode_base64(value))


def test_decoded_byte_limit_is_enforced():
    # Base64 length may round to the same bound; decoded length still matters.
    raw = b'x' * (module.MAX_IMAGE_BYTES + 1)
    assert_error('image_too_large', lambda: module._decode_base64(encoded(raw)))


@pytest.mark.parametrize('format', ['JPEG', 'PNG'])
def test_supported_images_decode_as_private_contiguous_bgr(format):
    bgr = module._decode_image(picture(format=format))
    assert bgr.shape == (160, 160, 3)
    assert bgr.dtype == np.uint8 and bgr.flags.c_contiguous
    assert tuple(bgr[0, 0]) == pytest.approx((200, 150, 100), abs=3)


@pytest.mark.parametrize('raw', [b'not an image', b'<svg xmlns="http://www.w3.org/2000/svg"/>', picture(format='GIF'), picture()[:-30]])
def test_malformed_truncated_and_other_formats_are_rejected(raw):
    assert_error('invalid_image', lambda: module._decode_image(raw))


@pytest.mark.parametrize('size', [(95, 200), (4100, 100), (2100, 2100)])
def test_image_dimensions_checked_before_processing(size):
    assert_error('image_dimensions', lambda: module._decode_image(picture(size)))


def test_processing_size_is_bounded_and_metadata_removed(adapter):
    exif = Image.Exif()
    exif[270] = 'Private image description should never remain'
    exif[274] = 6  # Rotate 90 degrees using EXIF, then strip the metadata.
    raw = picture((1600, 1000), 'JPEG', exif=exif)
    prepared = adapter.prepare_reference(encoded(raw))
    with Image.open(io.BytesIO(prepared)) as decoded:
        assert decoded.format == 'JPEG'
        assert decoded.size == (800, 1280)
        assert not decoded.getexif()
        assert 'Private image' not in str(decoded.info)
    assert b'Private image description' not in prepared


def test_single_image_only_no_animated_png():
    out = io.BytesIO()
    Image.new('RGB', (160, 160), 'red').save(out, 'PNG', save_all=True, append_images=[Image.new('RGB', (160, 160), 'blue')])
    assert_error('invalid_image', lambda: module._decode_image(out.getvalue()))


def test_reference_requires_face_and_feature(adapter):
    result = adapter.prepare_reference(encoded())
    assert result.startswith(b'\xff\xd8')
    adapter.detector.detect.assert_called_once()
    adapter.recognizer.alignCrop.assert_called_once()
    adapter.recognizer.feature.assert_called_once()
    assert not any('feature' in name for name in vars(adapter))


@pytest.mark.parametrize('detected', [None, np.empty((0, 15), dtype=np.float32)])
def test_absent_face_rejected(adapter, detected):
    adapter.detector.detect.return_value = (0, detected)
    assert_error('no_face', lambda: adapter.prepare_reference(encoded()))
    adapter.recognizer.feature.assert_not_called()


def test_multiple_faces_rejected(adapter):
    one = adapter.detector.detect.return_value[1]
    adapter.detector.detect.return_value = (2, np.vstack([one, one]))
    assert_error('multiple_faces', lambda: adapter.prepare_reference(encoded()))
    adapter.recognizer.feature.assert_not_called()


@pytest.mark.parametrize('position,value', [(0, float('nan')), (2, 30), (3, 30), (14, .89), (0, -60)])
def test_face_quality_failures_rejected(adapter, position, value):
    detected = adapter.detector.detect.return_value[1].copy()
    detected[0, position] = value
    adapter.detector.detect.return_value = (1, detected)
    assert_error('image_quality', lambda: adapter.prepare_reference(encoded()))


@pytest.mark.parametrize('feature', [None, np.zeros((1, 128)), np.full((1, 128), float('nan'))])
def test_invalid_features_rejected(adapter, feature):
    adapter.recognizer.feature.return_value = feature
    assert_error('image_quality', lambda: adapter.prepare_reference(encoded()))


@pytest.mark.parametrize('score,expected', [(.9, True), (.5, True), (.49999, False), (.1, False), (-.8, False)])
def test_cosine_decision_uses_recognizer_and_server_threshold(adapter, score, expected):
    adapter.recognizer.match.return_value = score
    assert adapter.compare(picture(), encoded()) is expected
    assert adapter.detector.detect.call_count == 2
    assert adapter.recognizer.feature.call_count == 2
    adapter.recognizer.match.assert_called_once()
    assert not any('feature' in name for name in vars(adapter))


@pytest.mark.parametrize('score', [float('nan'), float('inf'), 7])
def test_invalid_comparison_result_never_accepts(adapter, score):
    adapter.recognizer.match.return_value = score
    assert_error('unavailable', lambda: adapter.compare(picture(), encoded()), 503)


def test_detector_exception_is_sanitized_not_fallback(adapter):
    sensitive = 'private image or model path'
    adapter.detector.detect.side_effect = RuntimeError(sensitive)
    error = assert_error('unavailable', lambda: adapter.compare(picture(), encoded()), 503)
    assert sensitive not in str(error)
    adapter.recognizer.match.assert_not_called()


@pytest.mark.parametrize('threshold', ['nan', 'inf', '0', '0.363', '1', 'invalid'])
def test_invalid_or_relaxed_threshold_fails_closed(monkeypatch, threshold):
    monkeypatch.setenv('COMPAC_FACE_THRESHOLD', threshold)
    assert_error('invalid_configuration', module._threshold, 503)


def test_default_threshold_is_explicitly_experimental(monkeypatch):
    monkeypatch.delenv('COMPAC_FACE_THRESHOLD', raising=False)
    assert module._threshold() == .5
    monkeypatch.setenv('COMPAC_FACE_THRESHOLD', '.65')
    assert module._threshold() == .65


def test_missing_optional_dependencies_fail_closed(monkeypatch):
    monkeypatch.setattr(module.importlib, 'import_module', Mock(side_effect=ImportError('private dependency path')))
    assert_error('unavailable', module._libraries, 503)


def test_models_are_verified_and_tampering_is_not_cached(tmp_path, monkeypatch):
    raw = b'fake-weight-bytes-not-a-real-model'
    file = tmp_path / 'test.onnx'
    file.write_bytes(raw)
    monkeypatch.setattr(module, 'MODEL_FILES', ({'name': file.name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()},))
    assert module._verified_models(tmp_path) == [file]
    file.write_bytes(b'x' * len(raw))
    assert_error('unavailable', lambda: module._verified_models(tmp_path), 503)


def test_missing_model_does_not_download_or_accept(tmp_path):
    assert_error('unavailable', lambda: module._verified_models(tmp_path), 503)


def test_encryption_is_randomized_authenticated_and_bound_to_employee_version(cipher_key):
    raw = picture()
    encrypted = module.encrypt_reference(raw, 7, 'reference-version-one')
    other = module.encrypt_reference(raw, 7, 'reference-version-one')
    assert encrypted != other and encrypted.startswith('v1.')
    assert encoded(raw) not in encrypted and str(raw[:20]) not in encrypted
    assert module.decrypt_reference(encrypted, 7, 'reference-version-one') == raw
    assert_error('reference_integrity', lambda: module.decrypt_reference(encrypted, 8, 'reference-version-one'), 503)
    assert_error('reference_integrity', lambda: module.decrypt_reference(encrypted, 7, 'reference-version-two'), 503)


def test_reference_wrong_key_and_tampered_ciphertext_are_rejected(cipher_key, monkeypatch):
    encrypted = module.encrypt_reference(picture(), 7, 'version')
    raw = bytearray(base64.urlsafe_b64decode(encrypted[3:]))
    raw[-1] ^= 1
    assert_error('reference_integrity', lambda: module.decrypt_reference('v1.' + base64.urlsafe_b64encode(raw).decode(), 7, 'version'), 503)
    monkeypatch.setenv('COMPAC_FACE_KEY', base64.urlsafe_b64encode(os.urandom(32)).decode())
    assert_error('reference_integrity', lambda: module.decrypt_reference(encrypted, 7, 'version'), 503)


@pytest.mark.parametrize('key', ['', 'not-a-key', base64.urlsafe_b64encode(b'1' * 31).decode(), base64.urlsafe_b64encode(b'1' * 33).decode()])
def test_missing_or_invalid_key_never_uses_default_or_plaintext(monkeypatch, key):
    monkeypatch.setenv('COMPAC_FACE_KEY', key)
    assert_error('invalid_configuration', lambda: module.encrypt_reference(picture(), 1, 'version'), 503)


@pytest.mark.parametrize('employee,version', [(0, 'v'), (True, 'v'), (1, ''), (1, 'x' * 129)])
def test_encryption_context_is_checked(cipher_key, employee, version):
    assert_error('reference_integrity', lambda: module.encrypt_reference(picture(), employee, version), 503)


def test_unpadded_urlsafe_key_supported(cipher_key, monkeypatch):
    monkeypatch.setenv('COMPAC_FACE_KEY', os.environ['COMPAC_FACE_KEY'].rstrip('='))
    encrypted = module.encrypt_reference(picture(), 1, 'v')
    assert module.decrypt_reference(encrypted, 1, 'v') == picture()


@pytest.mark.parametrize('value', ['', 'v0.bad', 'v1.%%%', 'v1.' + base64.urlsafe_b64encode(b'short').decode()])
def test_invalid_ciphertext_is_safe(cipher_key, value):
    assert_error('reference_integrity', lambda: module.decrypt_reference(value, 1, 'v'), 503)


def test_configuration_reports_bounded_failure_without_secrets(monkeypatch):
    secret = 'invalid-private-secret-value'
    monkeypatch.setenv('COMPAC_FACE_KEY', secret)
    info = module.face_configuration()
    assert info['ready'] is False and info['anti_spoofing'] is False
    assert info['algorithm'] == module.ALGORITHM and info['threshold'] is None
    assert secret not in repr(info)


def test_actual_models_reject_geometric_image(monkeypatch):
    directory = os.getenv('COMPAC_FACE_TEST_MODELS_DIR')
    if not directory:
        pytest.skip('Set COMPAC_FACE_TEST_MODELS_DIR for actual-model smoke with geometric pixels.')
    monkeypatch.setenv('COMPAC_FACE_MODELS_DIR', directory)
    engine = module.get_engine()
    assert_error('no_face', lambda: engine.prepare_reference(encoded()))
