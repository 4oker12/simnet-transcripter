# Quick Start

STATUS

```bash
./status.sh
```

BASELINE / SIMNET

```bash
./profile.sh baseline
./profile.sh simnet
```

TRANSCRIBE / RESTART / LOG

```bash
./transcribe.sh path/to/call.mp3 simnet
./restart.sh
tail -f logs/server.log
```

GIT STATUS / PULL / SAVE TO GITHUB

```bash
./repo.sh status
./repo.sh pull
./repo.sh save "message"
```

## ASR profiles and API

Profiles live in `config/asr_profiles.json`. `baseline` uses vanilla large-v3; `simnet` uses the same loaded model with a small domain vocabulary. Changing the default with `profile.sh` is immediate and does not reload the model.

- `GET /health` reports runtime and default profile.
- `GET /profiles` lists available settings.
- `POST /transcribe` accepts a file, `language=auto|ru|uk`, and optional `profile=baseline|simnet`.

The backend loads exactly one `WhisperModel` on process start and serializes GPU inference. Request-level profile selection changes transcription parameters, not model lifecycle.

## Architecture and safety

GitHub stores reproducible source code, configuration, scripts, documentation, and history. Vast provides the GPU, CUDA runtime, model weights, and private runtime data.

The repository excludes `models/`, audio, `test_audio/`, `results/`, `logs/`, environments, caches, archives, and secrets. Keep credentials in an untracked `.env` if ever needed.

## Restore on a new GPU

```bash
git clone https://github.com/4oker12/simnet-transcripter.git simnet-transcriber
cd simnet-transcriber
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
# Obtain large-v3 in models/ using your normal model provisioning process.
# Install/adapt the supplied supervisor launcher, then:
./start.sh
curl -fsS http://127.0.0.1:8000/health | jq .
```

The supervisor files document the current Vast integration; adjust environment paths only when the new image differs.
