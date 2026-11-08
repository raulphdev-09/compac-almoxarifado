"""Local YuNet/SFace comparison and encrypted reference photographs.

No frames, embeddings or scores are persisted here. This engine has no liveness
or presentation-attack protection and is suitable only for supervised experiments.
Heavy optional libraries are imported lazily so ordinary warehouse use is intact.
"""
import base64
import binascii
import hashlib
import importlib
import io
import math
import os
from pathlib import Path
import re
import threading
import warnings


ALGORITHM = 'OPENCV_SFACE_YUNET_V1'
ZOO_COMMIT = '48b10fa505aeb51fbd127fc60a5c660040e823b7'
MODEL_FILES = (
    {
        'name': 'face_detection_yunet_2023mar.onnx',
        'folder': 'face_detection_yunet',
        'sha256': '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4',
        'size': 232589,
        'license': 'MIT',
    },
    {
        'name': 'face_recognition_sface_2021dec.onnx',
        'folder': 'face_recognition_sface',
        'sha256': '0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79',
        'size': 38696353,
        'license': 'Apache-2.0',
    },
)
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_BASE64_LENGTH = 4 * ((MAX_IMAGE_BYTES + 2) // 3)
MAX_IMAGE_PIXELS = 4_000_000
MAX_IMAGE_SIDE = 4096
MIN_IMAGE_SIDE = 96
MAX_PROCESSING_SIDE = 1280
_ENGINE = None
_ENGINE_KEY = None
_ENGINE_LOCK = threading.Lock()
_MODEL_CHECKS = {}


class FaceError(Exception):
    """A bounded error that never contains images, vectors, paths or secrets."""

    def __init__(self, code, message, status_code=422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _unavailable():
    return FaceError('unavailable', 'Comparação facial indisponível. Solicite avaliação ao administrador.', 503)


def _libraries():
    try:
        cv = importlib.import_module('cv2')
        np = importlib.import_module('numpy')
        pil_image = importlib.import_module('PIL.Image')
        pil_ops = importlib.import_module('PIL.ImageOps')
        if not hasattr(cv, 'FaceDetectorYN') or not hasattr(cv, 'FaceRecognizerSF'):
            raise ImportError('Required OpenCV interfaces unavailable')
        return cv, np, pil_image, pil_ops
    except (ImportError, OSError):
        raise _unavailable() from None


def model_directory():
    default = Path(__file__).resolve().parents[2] / '.data' / 'face-models'
    return Path(os.getenv('COMPAC_FACE_MODELS_DIR') or default).expanduser().resolve()


def _threshold():
    try:
        threshold = float(os.getenv('COMPAC_FACE_THRESHOLD', '0.5'))
    except (TypeError, ValueError):
        raise FaceError('invalid_configuration', 'Configuração de comparação facial inválida.', 503) from None
    # 0.363 is the upstream LFW example, not a COMPAC-calibrated acceptance
    # rate. Do not allow configuration to relax even that example threshold.
    if not math.isfinite(threshold) or not 0.363 < threshold <= 0.99:
        raise FaceError('invalid_configuration', 'Configuração de comparação facial inválida.', 503)
    return threshold


def _verified_models(directory):
    paths = []
    try:
        for model in MODEL_FILES:
            path = directory / model['name']
            info = path.stat()
            signature = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            if info.st_size != model['size']:
                raise _unavailable()
            if _MODEL_CHECKS.get(path) != signature:
                if hashlib.sha256(path.read_bytes()).hexdigest() != model['sha256']:
                    raise _unavailable()
                _MODEL_CHECKS[path] = signature
            paths.append(path)
    except (OSError, ValueError):
        raise _unavailable() from None
    return paths


def _decode_base64(value):
    if not isinstance(value, str) or not value or len(value) > MAX_BASE64_LENGTH:
        raise FaceError('invalid_image', 'Envie uma imagem JPEG ou PNG de até 2 MiB.')
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise FaceError('invalid_image', 'Envie uma imagem JPEG ou PNG válida.') from None
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise FaceError('image_too_large', 'A imagem excede o limite de 2 MiB.')
    return raw


def _decode_image(raw):
    """Validate header dimensions before allocating and strip image metadata."""
    _, np, image_lib, image_ops = _libraries()
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_IMAGE_BYTES:
        raise FaceError('invalid_image', 'Envie uma imagem JPEG ou PNG de até 2 MiB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', image_lib.DecompressionBombWarning)
            with image_lib.open(io.BytesIO(raw)) as probe:
                if probe.format not in ('JPEG', 'PNG') or getattr(probe, 'n_frames', 1) != 1:
                    raise FaceError('invalid_image', 'Envie uma única imagem JPEG ou PNG.')
                width, height = probe.size
                if (min(width, height) < MIN_IMAGE_SIDE or max(width, height) > MAX_IMAGE_SIDE
                        or width * height > MAX_IMAGE_PIXELS):
                    raise FaceError('image_dimensions', 'Use uma imagem de 96 a 4096 pixels por lado e até quatro megapixels.')
                probe.verify()
            with image_lib.open(io.BytesIO(raw)) as source:
                image = image_ops.exif_transpose(source).convert('RGB')
                image.thumbnail((MAX_PROCESSING_SIDE, MAX_PROCESSING_SIDE), image_lib.Resampling.LANCZOS)
                # np.array makes a private copy detached from Pillow's buffers.
                rgb = np.array(image, dtype=np.uint8)
        return np.ascontiguousarray(rgb[:, :, ::-1])
    except FaceError:
        raise
    except Exception:
        raise FaceError('invalid_image', 'Não foi possível validar a imagem JPEG ou PNG.') from None


def _encode_jpeg(bgr):
    cv, _, _, _ = _libraries()
    try:
        ok, encoded = cv.imencode('.jpg', bgr, [cv.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise ValueError('Encoding unavailable')
        image = encoded.tobytes()
        if len(image) > MAX_IMAGE_BYTES:
            raise FaceError('image_too_large', 'A imagem normalizada excede o limite de 2 MiB.')
        return image
    except FaceError:
        raise
    except Exception:
        raise _unavailable() from None


class FaceEngine:
    """CPU detector/recognizer. Its lock guards mutable OpenCV DNN instances."""

    def __init__(self):
        self.cv, self.np, _, _ = _libraries()
        self.threshold = _threshold()
        detector_path, recognition_path = _verified_models(model_directory())
        try:
            self.detector = self.cv.FaceDetectorYN.create(str(detector_path), '', (320, 320), 0.9, 0.3, 5000)
            self.recognizer = self.cv.FaceRecognizerSF.create(str(recognition_path), '')
        except Exception:
            raise _unavailable() from None
        self._lock = threading.Lock()

    def _feature(self, image):
        np = self.np
        height, width = image.shape[:2]
        self.detector.setInputSize((width, height))
        _, detected = self.detector.detect(image)
        if detected is None or len(detected) == 0:
            raise FaceError('no_face', 'Nenhum rosto foi identificado. Ajuste a posição e a iluminação.')
        if len(detected) != 1:
            raise FaceError('multiple_faces', 'Mantenha somente um rosto no enquadramento.')
        face = np.asarray(detected[0], dtype=np.float32)
        if face.size < 15 or not np.isfinite(face).all():
            raise FaceError('image_quality', 'O rosto não tem qualidade suficiente para comparação.')
        x, y, face_width, face_height = face[:4]
        eye_distance = float(np.linalg.norm(face[4:6] - face[6:8]))
        if (min(face_width, face_height) < 64 or eye_distance < 12 or face[-1] < 0.9
                or x < -0.1 * width or y < -0.1 * height
                or x + face_width > 1.1 * width or y + face_height > 1.1 * height):
            raise FaceError('image_quality', 'Aproxime o rosto e mantenha-o totalmente no enquadramento.')
        aligned = self.recognizer.alignCrop(image, face)
        feature = self.recognizer.feature(aligned)
        if feature is None or not np.isfinite(feature).all() or float(np.linalg.norm(feature)) <= 0:
            raise FaceError('image_quality', 'O rosto não tem qualidade suficiente para comparação.')
        return feature

    def prepare_reference(self, image_base64):
        image = _decode_image(_decode_base64(image_base64))
        if not self._lock.acquire(timeout=5):
            raise FaceError('busy', 'Comparador ocupado. Aguarde e tente novamente.', 429)
        try:
            self._feature(image)
        except FaceError:
            raise
        except Exception:
            raise _unavailable() from None
        finally:
            self._lock.release()
        return _encode_jpeg(image)

    def compare(self, reference_jpeg, image_base64):
        reference = _decode_image(reference_jpeg)
        candidate = _decode_image(_decode_base64(image_base64))
        if not self._lock.acquire(timeout=5):
            raise FaceError('busy', 'Comparador ocupado. Aguarde e tente novamente.', 429)
        try:
            reference_feature = self._feature(reference)
            candidate_feature = self._feature(candidate)
            similarity = float(self.recognizer.match(reference_feature, candidate_feature, self.cv.FaceRecognizerSF_FR_COSINE))
            if not math.isfinite(similarity) or not -1.0001 <= similarity <= 1.0001:
                raise _unavailable()
            return similarity >= self.threshold
        except FaceError:
            raise
        except Exception:
            raise _unavailable() from None
        finally:
            self._lock.release()


def get_engine():
    global _ENGINE, _ENGINE_KEY
    with _ENGINE_LOCK:
        directory = model_directory()
        paths = _verified_models(directory)
        try:
            key = (str(directory), _threshold(), *(path.stat().st_mtime_ns for path in paths))
        except OSError:
            raise _unavailable() from None
        if _ENGINE is None or _ENGINE_KEY != key:
            _ENGINE = FaceEngine()
            _ENGINE_KEY = key
        return _ENGINE


def _key():
    encoded = os.getenv('COMPAC_FACE_KEY', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}=?', encoded):
        raise FaceError('invalid_configuration', 'Chave privada de referências faciais indisponível.', 503)
    try:
        key = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
    except (ValueError, binascii.Error):
        raise FaceError('invalid_configuration', 'Chave privada de referências faciais indisponível.', 503) from None
    if len(key) != 32:
        raise FaceError('invalid_configuration', 'Chave privada de referências faciais indisponível.', 503)
    return key


def _cipher():
    try:
        return importlib.import_module('cryptography.hazmat.primitives.ciphers.aead').AESGCM(_key())
    except (ImportError, OSError):
        raise _unavailable() from None


def _associated_data(employee_id, version):
    if not isinstance(employee_id, int) or isinstance(employee_id, bool) or employee_id <= 0 or not isinstance(version, str) or not 1 <= len(version) <= 128:
        raise FaceError('reference_integrity', 'Referência facial indisponível.', 503)
    return f'compac-face-reference-v1\0{employee_id}\0{version}'.encode()


def encrypt_reference(image, employee_id, version):
    if not isinstance(image, bytes) or not image or len(image) > MAX_IMAGE_BYTES:
        raise FaceError('invalid_image', 'Referência facial inválida.')
    associated = _associated_data(employee_id, version)
    nonce = os.urandom(12)
    encrypted = _cipher().encrypt(nonce, image, associated)
    return 'v1.' + base64.urlsafe_b64encode(nonce + encrypted).decode('ascii')


def decrypt_reference(value, employee_id, version):
    associated = _associated_data(employee_id, version)
    cipher = _cipher()
    try:
        if not isinstance(value, str) or not value.startswith('v1.') or len(value) > MAX_BASE64_LENGTH + 128:
            raise ValueError('Invalid encrypted reference')
        raw = base64.b64decode(value[3:], altchars=b'-_', validate=True)
        if len(raw) < 29:
            raise ValueError('Invalid encrypted reference')
        plaintext = cipher.decrypt(raw[:12], raw[12:], associated)
        if not plaintext or len(plaintext) > MAX_IMAGE_BYTES:
            raise ValueError('Invalid encrypted reference')
        return plaintext
    except Exception:
        raise FaceError('reference_integrity', 'Referência facial indisponível. Solicite atualização ao administrador.', 503) from None


def face_configuration():
    try:
        _cipher()
        engine = get_engine()
        return {'ready': True, 'reason': '', 'algorithm': ALGORITHM, 'threshold': engine.threshold, 'anti_spoofing': False}
    except FaceError as exc:
        return {'ready': False, 'reason': exc.message, 'code': exc.code, 'algorithm': ALGORITHM, 'threshold': None, 'anti_spoofing': False}
