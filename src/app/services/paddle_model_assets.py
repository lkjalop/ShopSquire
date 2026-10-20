"""Deployment-owned local OCR assets; image contents cannot choose model paths."""
import hashlib
import json
import os
from pathlib import Path
import re


class PaddleAssetError(ValueError):
    pass


def local_paddle_models():
    configured = os.getenv('CV_PADDLE_MODEL_MANIFEST')
    if not configured:
        raise PaddleAssetError('paddle_models_not_enrolled')
    try:
        path = Path(configured)
        if path.stat().st_size > 65536:
            raise ValueError('manifest too large')
        manifest = json.loads(path.read_text(encoding='utf-8'))
        result = {}
        for kind, prefix in (('detector', 'text_detection'), ('recognizer', 'text_recognition')):
            item = manifest[kind]
            name = item['model_name']
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', name):
                raise ValueError('invalid model identity')
            directory = Path(item['directory']).resolve(strict=True)
            files = item['files']
            if not directory.is_dir() or set(files) != {'inference.json', 'inference.pdiparams', 'inference.yml'}:
                raise ValueError('complete model files required')
            total = 0
            for filename, expected in files.items():
                artifact = directory / filename
                if artifact.is_symlink() or not artifact.is_file():
                    raise ValueError('regular local model file required')
                if not isinstance(expected, str) or not re.fullmatch(r'[a-f0-9]{64}', expected):
                    raise ValueError('model digest required')
                total += artifact.stat().st_size
                if total > 512 * 1024 * 1024:
                    raise ValueError('model exceeds worker budget')
                digest = hashlib.sha256()
                with artifact.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
                if digest.hexdigest() != expected:
                    raise PaddleAssetError('paddle_model_artifact_mismatch')
            result[prefix + '_model_name'] = name
            result[prefix + '_model_dir'] = str(directory)
        return result
    except PaddleAssetError:
        raise
    except (OSError, ValueError, TypeError, KeyError):
        raise PaddleAssetError('paddle_model_manifest_invalid') from None
