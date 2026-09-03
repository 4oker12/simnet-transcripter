# SIMNET Transcriber

GPU speech-to-text service used by SIMNET Workbench.

## Responsibility boundary

The service has one job:

`audio -> faster-whisper -> versioned transcript JSON`

It does **not** store UserSide/PBX cookies, does not register calls, and does not decide which subscriber owns a call. Those responsibilities stay in Workbench, where the canonical UserSide `call_list` identity and CALL binding rules already live.

This separation is intentional: a Vast GPU instance can be replaced without moving CRM credentials or business logic onto it.

## Quick start

```bash
make status
make health
make capabilities
make transcribe FILE=path/to/call.mp3 PROFILE=simnet LANGUAGE=auto
```

Existing direct scripts remain available:

```bash
./status.sh
./profile.sh baseline
./profile.sh simnet
./transcribe.sh path/to/call.mp3 simnet auto
./restart.sh
tail -f logs/server.log
```

Set `SIMNET_TRANSCRIBE_JSON=1` to print the complete API JSON from `transcribe.sh`.

## API

Profiles live in `config/asr_profiles.json`. `baseline` uses vanilla `large-v3`; `simnet` uses the same loaded model with a small domain vocabulary. Changing the default with `profile.sh` is immediate and does not reload the model.

- `GET /health` — service/runtime/model/GPU status.
- `GET /profiles` — available ASR profiles.
- `GET /capabilities` — API schema, formats, languages, upload limit and concurrency.
- `POST /transcribe` — multipart audio plus `language=auto|ru|uk` and optional `profile=baseline|simnet`.

A successful transcription returns evidence-oriented metadata in addition to text:

- `schema=simnet-transcript-v1`;
- `request_id`;
- `audio_sha256` and `file_bytes`;
- detected `language` and `language_probability`;
- duration, processing time and realtime factor;
- segment timestamps and full text.

Audio is written only to a temporary file for inference and deleted in `finally`. The default upload limit is 64 MiB and can be changed with `SIMNET_MAX_UPLOAD_MB`.

The backend loads exactly one `WhisperModel` on process start and serializes GPU inference. Request-level profile selection changes transcription parameters, not model lifecycle.

## Install / restore on Vast

From an existing checkout:

```bash
bash setup-transcriber.sh
```

The setup is idempotent: it checks disk space, installs only missing OS tools, reuses the active environment or `/venv/main` when available, installs Python requirements, installs the Supervisor launcher/config, performs a syntax check, starts the service and verifies `/capabilities`.

The supplied Supervisor launcher is path-configurable and defaults to the repository's actual Vast path:

```text
/workspace/simnet-transcripter
```

For diagnostics:

```bash
make full-check
# or
bash diagnostic.sh
```

## Workbench connection: keep port 8000 private

The backend listens on `127.0.0.1:8000`. Do not expose it directly to the Internet just to make the browser extension reach Vast.

From Windows PowerShell, open a local SSH tunnel:

```powershell
.\tools\open-workbench-tunnel.ps1 -Server <VAST_IP> -Port <SSH_PORT>
```

Then Workbench talks to `http://127.0.0.1:8000`; SSH carries that traffic to the GPU service. No PBX/UserSide credentials are copied to Vast.

## Architecture and safety

GitHub stores reproducible source code, configuration, scripts, documentation, and history. Vast provides the GPU, CUDA runtime, model weights, and private runtime data.

The repository excludes `models/`, audio, `test_audio/`, `results/`, `logs/`, environments, caches, archives, and secrets. Keep credentials in an untracked `.env` if ever needed.

A server-side `send-call.sh` is deliberately not part of the architecture. UserSide registration remains in Workbench so the transcript is attached only after the existing CALL correlation/binding checks have selected the correct subscriber.
