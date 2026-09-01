#!/usr/bin/env python3
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import torch
import nemo
import nemo.collections.asr as nemo_asr


ROOT = Path("/workspace/simnet-transcriber")
SOURCE_MP3 = ROOT / "test_audio/test.mp3"
INPUT_WAV = ROOT / "experiments/test-16k-mono.wav"
WARMUP_WAV = ROOT / "experiments/test-16k-mono-warmup.wav"
MODEL_FILE = ROOT / "models/parakeet-tdt-0.6b-v3/parakeet-tdt-0.6b-v3.nemo"
OUTPUT_TXT = ROOT / "results/parakeet-tdt-0.6b-v3.txt"
OUTPUT_JSON = ROOT / "results/parakeet-tdt-0.6b-v3.json"


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


class GpuMonitor:
    def __init__(self):
        self.stop_event = threading.Event()
        self.samples = []
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        while not self.stop_event.is_set():
            try:
                row = command(
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used",
                    "--format=csv,noheader,nounits",
                )
                util, memory = [int(x.strip()) for x in row.split(",")]
                self.samples.append({"utilization_percent": util, "memory_mib": memory})
            except Exception:
                pass
            self.stop_event.wait(0.20)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=2)


def first_hypothesis(output):
    if isinstance(output, tuple):
        output = output[0]
    if not isinstance(output, (list, tuple)) or not output:
        raise RuntimeError(f"Unexpected transcribe output: {type(output)!r}")
    return output[0]


def main():
    if OUTPUT_TXT.exists() or OUTPUT_JSON.exists():
        raise FileExistsError("Parakeet result already exists; refusing to overwrite")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; CPU fallback is forbidden")
    gpu_name = torch.cuda.get_device_name(0)
    if "A4000" not in gpu_name:
        raise RuntimeError(f"Unexpected GPU: {gpu_name}")

    duration = float(
        command(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(SOURCE_MP3),
        )
    )
    INPUT_WAV.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(SOURCE_MP3),
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(INPUT_WAV)],
        check=True,
    )
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(INPUT_WAV),
         "-t", "10", "-c:a", "pcm_s16le", str(WARMUP_WAV)],
        check=True,
    )

    monitor = GpuMonitor()
    monitor.start()
    load_started = time.perf_counter()
    model = nemo_asr.models.ASRModel.restore_from(
        restore_path=str(MODEL_FILE), map_location=torch.device("cuda")
    )
    model = model.to("cuda").eval()
    model.change_attention_model(
        self_attention_model="rel_pos_local_attn",
        att_context_size=[256, 256],
    )
    load_seconds = time.perf_counter() - load_started

    parameter = next(model.parameters())
    if parameter.device.type != "cuda":
        raise RuntimeError(f"Model is not on CUDA: {parameter.device}")

    with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.float16):
        warm_started = time.perf_counter()
        model.transcribe(
            audio=[str(WARMUP_WAV)], batch_size=1, return_hypotheses=True,
            num_workers=0, verbose=False, timestamps=True,
        )
        warmup_seconds = time.perf_counter() - warm_started
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        output = model.transcribe(
            audio=[str(INPUT_WAV)], batch_size=1, return_hypotheses=True,
            num_workers=0, verbose=True, timestamps=True,
        )
        processing_seconds = time.perf_counter() - started

    peak_allocated = torch.cuda.max_memory_allocated() / (1024 ** 2)
    peak_reserved = torch.cuda.max_memory_reserved() / (1024 ** 2)
    monitor.stop()
    hypothesis = first_hypothesis(output)
    text = hypothesis.text if hasattr(hypothesis, "text") else str(hypothesis)
    timestamps = json_safe(getattr(hypothesis, "timestamp", None))
    segments = timestamps.get("segment", []) if isinstance(timestamps, dict) else []

    language_fields = {}
    for attr in ("language", "lang", "langs", "language_id", "language_code"):
        if hasattr(hypothesis, attr):
            language_fields[attr] = json_safe(getattr(hypothesis, attr))

    peak_util = max((s["utilization_percent"] for s in monitor.samples), default=None)
    peak_total_vram = max((s["memory_mib"] for s in monitor.samples), default=None)
    result = {
        "ok": True,
        "profile": "parakeet-tdt-0.6b-v3",
        "model": "nvidia/parakeet-tdt-0.6b-v3",
        "model_revision": "541d1f99c6b0c3cd0b11a95167540bb8edefd82b",
        "model_file": str(MODEL_FILE),
        "runtime": {"nemo": nemo.__version__, "torch": torch.__version__},
        "device": "cuda",
        "gpu": gpu_name,
        "parameter_device": str(parameter.device),
        "parameter_dtype": str(parameter.dtype),
        "inference_autocast": "float16",
        "source_audio": str(SOURCE_MP3),
        "inference_audio": str(INPUT_WAV),
        "preprocessing": "ffmpeg mono PCM s16le 16000 Hz from the source MP3",
        "audio_duration_seconds": duration,
        "model_load_seconds": round(load_seconds, 6),
        "warmup_seconds": round(warmup_seconds, 6),
        "processing_seconds": round(processing_seconds, 6),
        "realtime_factor": round(processing_seconds / duration, 6),
        "attention": {"self_attention_model": "rel_pos_local_attn", "att_context_size": [256, 256]},
        "decoding": "checkpoint default TDT decoder; no phrase boosting/context biasing",
        "language_behavior": "automatic multilingual recognition; no language was forced",
        "detected_language_fields": language_fields,
        "language_probability": None,
        "segment_count": len(segments),
        "timestamps": timestamps,
        "gpu_peak_utilization_percent": peak_util,
        "gpu_peak_total_vram_mib": peak_total_vram,
        "torch_peak_allocated_mib": round(peak_allocated, 2),
        "torch_peak_reserved_mib": round(peak_reserved, 2),
        "gpu_monitor_samples": len(monitor.samples),
        "text": text,
    }
    tmp_txt = OUTPUT_TXT.with_suffix(".txt.tmp")
    tmp_json = OUTPUT_JSON.with_suffix(".json.tmp")
    tmp_txt.write_text(text.strip() + "\n", encoding="utf-8")
    tmp_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_txt, OUTPUT_TXT)
    os.replace(tmp_json, OUTPUT_JSON)
    print(json.dumps({k: result[k] for k in (
        "ok", "gpu", "parameter_device", "parameter_dtype", "audio_duration_seconds",
        "model_load_seconds", "warmup_seconds", "processing_seconds", "realtime_factor",
        "segment_count", "gpu_peak_utilization_percent", "gpu_peak_total_vram_mib",
        "torch_peak_allocated_mib", "torch_peak_reserved_mib", "detected_language_fields",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
