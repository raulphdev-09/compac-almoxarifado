"""Explicit, checksum-pinned model installation; never called by the server."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.attendance.face_engine import MODEL_FILES, ZOO_COMMIT, model_directory


def download(url, target, *, expected_sha256=None, expected_size=None):
    temporary = None
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.compac-model-', delete=False) as out:
                temporary = Path(out.name)
                digest = hashlib.sha256()
                length = 0
                while chunk := response.read(1024 * 1024):
                    length += len(chunk)
                    if length > (expected_size or 128 * 1024):
                        raise RuntimeError('Download excedeu o tamanho esperado.')
                    digest.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
        if ((expected_size is not None and length != expected_size)
                or (expected_sha256 and digest.hexdigest() != expected_sha256)):
            raise RuntimeError('Checksum ou tamanho do modelo não corresponde à revisão fixada.')
        temporary.replace(target)
        return digest.hexdigest()
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dir', type=Path, help='Diretório privado de destino; padrão COMPAC_FACE_MODELS_DIR ou .data/face-models')
    args = parser.parse_args()
    directory = (args.dir or model_directory()).expanduser().resolve()
    # Never publish model files or notices as application static resources.
    static = ROOT / 'app' / 'static'
    if directory == static or static in directory.parents:
        parser.error('Use um diretório privado fora de app/static.')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest = {'opencv_zoo_commit': ZOO_COMMIT, 'models': []}
    for model in MODEL_FILES:
        base = f'https://media.githubusercontent.com/media/opencv/opencv_zoo/{ZOO_COMMIT}/models/{model["folder"]}/'
        target = directory / model['name']
        if not (target.is_file() and target.stat().st_size == model['size'] and hashlib.sha256(target.read_bytes()).hexdigest() == model['sha256']):
            download(base + model['name'], target, expected_sha256=model['sha256'], expected_size=model['size'])
        # Sources are fixed at the same commit, preserving each model's notice.
        notice_url = f'https://raw.githubusercontent.com/opencv/opencv_zoo/{ZOO_COMMIT}/models/{model["folder"]}/LICENSE'
        download(notice_url, directory / (model['folder'] + '-LICENSE'))
        manifest['models'].append(dict(model, url=base + model['name']))
        print(f'Verificado: {model["name"]} ({model["license"]}).')
    manifest_path = directory / 'models.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print('Modelos instalados. Esta operação não ativa o ponto nem altera o banco.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError):
        print('Falha ao instalar os modelos. Verifique rede, diretório e checksums; nada será aprovado por substituição.', file=sys.stderr)
        raise SystemExit(1)
