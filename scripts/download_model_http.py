"""Resumable HTTP Range fallback; no Xet. Only run with the API stopped."""
import concurrent.futures
import fcntl
import os
from pathlib import Path
import time
import httpx
from verify_model import MODEL, FILES, verify

REV = 'edaa852ec7e145841d8ffdb056a99866b5f0a478'
BASE = f'https://huggingface.co/Systran/faster-whisper-large-v3/resolve/{REV}'
SIZE = FILES['model.bin'][0]
CHUNK = 32 * 1024 * 1024
PARTS = MODEL / '.http-parts'

def part(index):
    start = index * CHUNK
    end = min(SIZE, start + CHUNK) - 1
    dest = PARTS / f'{index:04d}.part'
    if dest.exists() and dest.stat().st_size == end - start + 1:
        return index
    tmp = dest.with_suffix('.incomplete')
    for attempt in range(4):
        try:
            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, connect=20)) as client:
                with client.stream('GET', f'{BASE}/model.bin?download=true&range_start={start}',
                                   headers={'Range': f'bytes={start}-{end}'}) as response:
                    response.raise_for_status()
                    assert response.status_code == 206, response.status_code
                    assert response.headers['content-range'] == f'bytes {start}-{end}/{SIZE}'
                    with tmp.open('wb') as stream:
                        for data in response.iter_bytes(1024 * 1024):
                            stream.write(data)
            assert tmp.stat().st_size == end - start + 1
            tmp.replace(dest)
            print(f'Part {index}: {end-start+1} bytes OK', flush=True)
            return index
        except Exception as exc:
            print(f'Part {index} attempt {attempt+1}: {type(exc).__name__}', flush=True)
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))

if __name__ == '__main__':
    with Path('/tmp/simnet-model-recovery.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        MODEL.mkdir(parents=True, exist_ok=True)
        PARTS.mkdir(exist_ok=True)
        for name, (size, _) in FILES.items():
            if name == 'model.bin':
                continue
            p = MODEL / name
            if p.exists() and p.stat().st_size == size:
                continue
            with httpx.Client(follow_redirects=True, timeout=60) as client:
                response = client.get(f'{BASE}/{name}')
                response.raise_for_status()
                assert len(response.content) == size
                p.write_bytes(response.content)
        count = (SIZE + CHUNK - 1) // CHUNK
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(part, range(count)))
        tmp = MODEL / 'model.bin.incomplete'
        with tmp.open('wb') as output:
            for index in range(count):
                with (PARTS / f'{index:04d}.part').open('rb') as source:
                    while chunk := source.read(8 * 1024 * 1024):
                        output.write(chunk)
        import hashlib
        h = hashlib.sha256()
        with tmp.open('rb') as source:
            while chunk := source.read(8 * 1024 * 1024):
                h.update(chunk)
        assert tmp.stat().st_size == SIZE and h.hexdigest() == FILES['model.bin'][1]
        tmp.replace(MODEL / 'model.bin')
        verify()
        print('Verified HTTP model. Range parts retained until explicit cleanup.', flush=True)
