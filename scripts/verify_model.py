"""Verify pinned Systran/faster-whisper-large-v3 files without network access."""
import hashlib
import json
from pathlib import Path

MODEL = Path('/workspace/simnet-transcriber/models/faster-whisper-large-v3')
FILES = {
    '.gitattributes': (1519, 'a6344aac8c09253b3b630fb776ae94478aa0275b'),
    'README.md': (2052, 'a84bfa7f20cac02ea5a99efa5eaf687ad58c1caf'),
    'config.json': (2394, '75336feae814999bae6ccccdecf177639ffc6f9d'),
    'model.bin': (3087284237, '69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1'),
    'preprocessor_config.json': (340, '931c77a740890c46365c7ae0c9d350ba3cca908f'),
    'tokenizer.json': (2480617, '3a5e2ba63acdcac9a19ba56cf9bd27f185bfff61'),
    'vocabulary.json': (1068114, '0adcd01e7c237205d593b707e66dd5d7bc785d2d'),
}

def verify():
    print('Model:', MODEL)
    assert MODEL.is_dir(), MODEL
    for p in MODEL.rglob('*'):
        assert not p.is_symlink(), f'Symlink: {p}'
        assert not p.name.endswith('.incomplete'), f'Incomplete: {p}'
    for name, (size, expected) in FILES.items():
        p = MODEL / name
        assert p.is_file() and not p.is_symlink(), p
        assert p.stat().st_size == size, f'Size mismatch: {p}'
        digest = hashlib.sha256() if name == 'model.bin' else hashlib.sha1(f'blob {size}\0'.encode())
        with p.open('rb') as stream:
            while chunk := stream.read(8 * 1024 * 1024):
                digest.update(chunk)
        assert digest.hexdigest() == expected, f'Hash mismatch: {p}'
        if name.endswith('.json'):
            json.loads(p.read_text())
        print(name, size, digest.hexdigest(), 'OK')
    print('VERIFIED; incomplete=0; symlinks=0')

if __name__ == '__main__':
    verify()
