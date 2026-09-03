import asyncio
import hashlib
import json
import logging
import os
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parent
LOG_DIR, TMP_DIR, MODEL_DIR = ROOT / "logs", ROOT / "tmp", ROOT / "models"
PROFILE_CONFIG = ROOT / "config" / "asr_profiles.json"
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".webm", ".flac"}
ALLOWED_LANGUAGES = {"auto", "uk", "ru"}
APP_VERSION = "1.2.0"
TRANSCRIPT_SCHEMA = "simnet-transcript-v1"
UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_UPLOAD_MB = max(1, int(os.getenv("SIMNET_MAX_UPLOAD_MB", "64")))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

for directory in (LOG_DIR, TMP_DIR, MODEL_DIR):
    directory.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "server.log", encoding="utf-8"),
    ],
    force=True,
)
logger = logging.getLogger("simnet-transcriber")


class RuntimeState:
    model: WhisperModel | None = None
    gpu_name = "unknown"
    model_name = "unknown"
    device = "unknown"
    compute_type = "unknown"


state = RuntimeState()
inference_lock = asyncio.Lock()


def read_profiles() -> dict[str, Any]:
    try:
        config = json.loads(PROFILE_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read profile config: {exc}") from exc

    profiles, default = config.get("profiles"), config.get("default")
    if not isinstance(profiles, dict) or not profiles or default not in profiles:
        raise RuntimeError("profile config must contain profiles and a valid default")

    shared = None
    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            raise RuntimeError(f"profile {name!r} must be an object")
        model_key = (
            profile.get("model"),
            profile.get("device"),
            profile.get("compute_type"),
        )
        if shared is None:
            shared = model_key
        elif model_key != shared:
            raise RuntimeError("all profiles must share one model/device/compute_type")
    return config


def public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": profile["model"],
        "device": profile["device"],
        "compute_type": profile["compute_type"],
        "vad_filter": bool(profile.get("vad_filter", True)),
        "hotwords": profile.get("hotwords"),
    }


def get_gpu_name() -> str:
    try:
        return subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            text=True,
            timeout=10,
        ).strip().splitlines()[0]
    except Exception:
        logger.exception("Unable to query GPU name")
        return "unknown"


def load_model() -> WhisperModel:
    config = read_profiles()
    profile = config["profiles"][config["default"]]
    state.model_name = profile["model"]
    state.device = profile["device"]
    state.compute_type = profile["compute_type"]
    logger.info(
        "Loading one shared model: model=%s device=%s compute_type=%s",
        state.model_name,
        state.device,
        state.compute_type,
    )
    started = time.perf_counter()
    model = WhisperModel(
        state.model_name,
        device=state.device,
        compute_type=state.compute_type,
        download_root=str(MODEL_DIR),
    )
    logger.info("Model loaded successfully in %.3f seconds", time.perf_counter() - started)
    return model


@asynccontextmanager
async def lifespan(_: FastAPI):
    state.gpu_name = get_gpu_name()
    state.model = await asyncio.to_thread(load_model)
    logger.info("Backend ready on 127.0.0.1:8000 using %s", state.gpu_name)
    yield
    logger.info("Backend shutdown")
    state.model = None


app = FastAPI(title="Simnet Transcriber", version=APP_VERSION, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    config = read_profiles()
    return {
        "ok": state.model is not None,
        "service": "simnet-transcriber",
        "version": APP_VERSION,
        "schema": TRANSCRIPT_SCHEMA,
        "model": state.model_name,
        "device": state.device,
        "compute_type": state.compute_type,
        "gpu": state.gpu_name,
        "default_profile": config["default"],
    }


@app.get("/profiles")
async def profiles() -> dict[str, Any]:
    config = read_profiles()
    return {
        "default": config["default"],
        "profiles": {
            name: public_profile(profile)
            for name, profile in config["profiles"].items()
        },
    }


@app.get("/capabilities")
async def capabilities() -> dict[str, Any]:
    config = read_profiles()
    return {
        "service": "simnet-transcriber",
        "version": APP_VERSION,
        "transcript_schema": TRANSCRIPT_SCHEMA,
        "supported_extensions": sorted(ALLOWED_EXTENSIONS),
        "supported_languages": sorted(ALLOWED_LANGUAGES),
        "profiles": sorted(config["profiles"].keys()),
        "default_profile": config["default"],
        "max_upload_mb": MAX_UPLOAD_MB,
        "max_concurrent_inference": 1,
        "audio_persisted": False,
    }


def probe_duration(path: str) -> float | None:
    try:
        value = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            text=True,
            timeout=30,
        ).strip()
        return float(value)
    except Exception:
        logger.exception("ffprobe failed for %s", path)
        return None


def transcribe_file(
    path: str,
    language: str,
    profile_name: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    if state.model is None:
        raise RuntimeError("Model is not loaded")

    duration = probe_duration(path)
    hotwords = profile.get("hotwords")
    started = time.perf_counter()
    segments_iter, info = state.model.transcribe(
        path,
        language=None if language == "auto" else language,
        vad_filter=bool(profile.get("vad_filter", True)),
        hotwords=", ".join(hotwords) if hotwords else None,
        beam_size=5,
    )

    segment_rows, text_parts = [], []
    for segment in segments_iter:
        clean_text = segment.text.strip()
        segment_rows.append(
            {
                "id": segment.id,
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "text": clean_text,
            }
        )
        if clean_text:
            text_parts.append(clean_text)

    processing_seconds = time.perf_counter() - started
    if duration is None:
        duration = float(info.duration)

    return {
        "ok": True,
        "schema": TRANSCRIPT_SCHEMA,
        "profile": profile_name,
        "language": info.language,
        "language_probability": round(float(getattr(info, "language_probability", 0.0) or 0.0), 6),
        "duration_seconds": round(duration, 3),
        "processing_seconds": round(processing_seconds, 3),
        "realtime_factor": round(processing_seconds / duration, 4) if duration else None,
        "text": " ".join(text_parts),
        "segments": segment_rows,
    }


async def save_upload_to_temp(file: UploadFile, suffix: str) -> tuple[str, int, str]:
    temp_path = ""
    total_bytes = 0
    digest = hashlib.sha256()
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=suffix,
            prefix="upload_",
            dir=TMP_DIR,
            delete=False,
        ) as output:
            temp_path = output.name
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"audio file exceeds {MAX_UPLOAD_MB} MiB upload limit",
                    )
                digest.update(chunk)
                output.write(chunk)
        return temp_path, total_bytes, digest.hexdigest()
    except Exception:
        if temp_path:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
        raise


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    language: str = Form("auto"),
    profile: str | None = Form(None),
) -> dict[str, Any]:
    request_id = str(uuid4())
    requested_language = language.strip().lower()
    if requested_language not in ALLOWED_LANGUAGES:
        raise HTTPException(status_code=400, detail="language must be one of: auto, uk, ru")

    config = read_profiles()
    requested_profile = profile.strip().lower() if profile else config["default"]
    if requested_profile not in config["profiles"]:
        raise HTTPException(
            status_code=400,
            detail=f"profile must be one of: {', '.join(config['profiles'])}",
        )

    source_filename = Path(file.filename or "audio").name
    suffix = Path(source_filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="supported formats: mp3, wav, m4a, ogg, webm, flac",
        )

    async with inference_lock:
        temp_path = ""
        try:
            temp_path, file_bytes, audio_sha256 = await save_upload_to_temp(file, suffix)
            result = await asyncio.to_thread(
                transcribe_file,
                temp_path,
                requested_language,
                requested_profile,
                config["profiles"][requested_profile],
            )
            result.update(
                {
                    "request_id": request_id,
                    "source_filename": source_filename,
                    "file_bytes": file_bytes,
                    "audio_sha256": audio_sha256,
                }
            )
            logger.info(
                "Transcribed request=%s profile=%s language=%s duration=%.3fs processing=%.3fs bytes=%d sha256=%s segments=%d",
                request_id,
                requested_profile,
                result["language"],
                result["duration_seconds"],
                result["processing_seconds"],
                file_bytes,
                audio_sha256[:12],
                len(result["segments"]),
            )
            return result
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Transcription failed request=%s", request_id)
            raise HTTPException(status_code=500, detail=f"transcription failed: {exc}") from exc
        finally:
            await file.close()
            if temp_path:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass
