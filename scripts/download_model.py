"""Download the pinned model by HTTP; run only with the service stopped."""
import os
import time
import fcntl
from pathlib import Path

os.environ['HF_HUB_DISABLE_XET'] = '1'
os.environ['HF_HUB_OFFLINE'] = '0'
os.environ['HF_HUB_DOWNLOAD_TIMEOUT'] = '60'
os.environ['HF_HUB_ETAG_TIMEOUT'] = '30'
from huggingface_hub import snapshot_download
from verify_model import MODEL, verify

if __name__ == '__main__':
    with Path('/tmp/simnet-model-recovery.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for attempt in range(1, 5):
            try:
                snapshot_download(
                    'Systran/faster-whisper-large-v3',
                    revision='edaa852ec7e145841d8ffdb056a99866b5f0a478',
                    local_dir=str(MODEL), max_workers=2, etag_timeout=30,
                )
                break
            except Exception as exc:
                print(f'Attempt {attempt}: {type(exc).__name__}', flush=True)
                if attempt == 4:
                    raise
                time.sleep(5 * attempt)
        verify()
