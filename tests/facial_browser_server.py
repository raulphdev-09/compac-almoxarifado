"""Disposable browser-test server. Never a product or deployment entry point.

The injected adapter verifies UI/security contracts, not biometric accuracy.
COMPAC_BROWSER_NATIVE_FACE=1 uses the real local engine to test rejection.
"""
import base64
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if (os.getenv('COMPAC_ENV') != 'test'
        or os.getenv('COMPAC_ATTENDANCE_MODE') != 'facial'
        or os.getenv('DATABASE_URL', '').strip()
        or os.getenv('RENDER', '').lower() == 'true'):
    raise RuntimeError('This harness requires a disposable local test environment.')

from app.attendance import face_engine


class BrowserTestOnlyEngine:
    """Only injected by this explicit test harness. Does not recognize faces."""
    threshold = .5

    def prepare_reference(self, encoded):
        raw = base64.b64decode(encoded, validate=True)
        if not raw.startswith((b'\x89PNG', b'\xff\xd8')):
            raise face_engine.FaceError('invalid_image', 'Imagem de teste inválida.')
        return b'BROWSER_TEST_ONLY_NORMALIZED_REFERENCE_NOT_A_PHOTOGRAPH'

    def compare(self, reference, encoded):
        self.prepare_reference(encoded)
        assert reference == b'BROWSER_TEST_ONLY_NORMALIZED_REFERENCE_NOT_A_PHOTOGRAPH'
        return True


if os.getenv('COMPAC_BROWSER_NATIVE_FACE') != '1':
    engine = BrowserTestOnlyEngine()
    face_engine.get_engine = lambda: engine

from app.main import app

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ['COMPAC_BROWSER_FACE_PORT']), proxy_headers=False)
