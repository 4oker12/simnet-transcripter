#!/usr/bin/env python3
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import ctranslate2
from faster_whisper import WhisperModel


ROOT = Path("/workspace/simnet-transcriber")
AUDIO = ROOT / "test_audio/test2.mp3"
RESULTS = ROOT / "results"
MODEL_ROOT = ROOT / "models"

HOTWORDS = (
    "SIMNET, Сімнет, PlayStation, PS4, PS5, NAT, NAT type, тип NAT, IPv4, IPv6, "
    "MAC, MAC address, MAC-адрес, Cudy, MikroTik, TP-Link, ONU, ONT, OLT, GPON, "
    "EPON, GEPON, Juniper, BRAS, VLAN, DHCP, PPPoE, Wi-Fi, Ethernet, IP, IP-адрес, "
    "статический IP, выделенный IP, білий IP, мегабит, гигабит, роутер, оптика"
)

COMMON_PARAMETERS = {
    "language": None,
    "task": "transcribe",
    "beam_size": 5,
    "best_of": 5,
    "patience": 1.0,
    "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    "condition_on_previous_text": True,
    "initial_prompt": None,
    "word_timestamps": False,
    "vad_filter": True,
    "vad_parameters": None,
}

PROFILES = [
    {
        "profile": "test2-baseline-large-v3",
        "hotwords": None,
        "txt": RESULTS / "test2-baseline-large-v3.txt",
        "json": RESULTS / "test2-baseline-large-v3.json",
    },
    {
        "profile": "test2-large-v3-simnet-hotwords",
        "hotwords": HOTWORDS,
        "txt": RESULTS / "test2-large-v3-simnet-hotwords.txt",
        "json": RESULTS / "test2-large-v3-simnet-hotwords.json",
    },
]


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def gpu_snapshot():
    row = command(
        "nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ).splitlines()[0]
    name, utilization, used, total = [part.strip() for part in row.split(",")]
    return {
        "name": name,
        "utilization_percent": int(utilization),
        "memory_used_mib": int(used),
        "memory_total_mib": int(total),
    }


class GpuMonitor:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.peak_utilization = 0
        self.peak_memory_mib = 0
        self.samples = 0

    def run(self):
        while not self.stop_event.is_set():
            try:
                snap = gpu_snapshot()
                self.peak_utilization = max(self.peak_utilization, snap["utilization_percent"])
                self.peak_memory_mib = max(self.peak_memory_mib, snap["memory_used_mib"])
                self.samples += 1
            except Exception:
                pass
            self.stop_event.wait(0.20)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=10)


def atomic_create(path, content):
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(temporary, "x", encoding="utf-8") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run_profile(model, spec, audio_duration, model_load_seconds, idle_snapshot):
    parameters = dict(COMMON_PARAMETERS)
    parameters["hotwords"] = spec["hotwords"]
    monitor = GpuMonitor()
    monitor.start()
    try:
        started = time.perf_counter()
        segment_iter, info = model.transcribe(str(AUDIO), **parameters)
        segments = []
        text_parts = []
        for segment in segment_iter:
            text = segment.text.strip()
            segments.append({
                "id": segment.id,
                "seek": segment.seek,
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "text": text,
                "avg_logprob": round(segment.avg_logprob, 6),
                "compression_ratio": round(segment.compression_ratio, 6),
                "no_speech_prob": round(segment.no_speech_prob, 6),
            })
            if text:
                text_parts.append(text)
        processing = time.perf_counter() - started
    finally:
        monitor.stop()

    full_text = " ".join(text_parts)
    payload = {
        "ok": True,
        "profile": spec["profile"],
        "model": "large-v3",
        "device": "cuda",
        "compute_type": "float16",
        "gpu": idle_snapshot["name"],
        "ctranslate2_cuda_device_count": ctranslate2.get_cuda_device_count(),
        "language_setting": "auto",
        "detected_language": info.language,
        "language_probability": round(info.language_probability, 6),
        "transcribe_parameters": parameters,
        "audio_duration": round(audio_duration, 3),
        "duration_after_vad": round(info.duration_after_vad, 3),
        "model_load_seconds_shared": round(model_load_seconds, 3),
        "processing_time": round(processing, 3),
        "realtime_factor": round(processing / audio_duration, 4),
        "segment_count": len(segments),
        "gpu_idle_before_profiles_memory_mib_total": idle_snapshot["memory_used_mib"],
        "gpu_peak_utilization_percent": monitor.peak_utilization,
        "gpu_peak_memory_mib_total": monitor.peak_memory_mib,
        "gpu_monitor_samples": monitor.samples,
        "text": full_text,
        "segments": segments,
    }
    atomic_create(spec["txt"], full_text + "\n")
    atomic_create(spec["json"], json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: payload[key] for key in (
        "profile", "detected_language", "language_probability", "audio_duration",
        "duration_after_vad", "processing_time", "realtime_factor", "segment_count",
        "gpu_peak_utilization_percent", "gpu_peak_memory_mib_total",
    )}, ensure_ascii=False, indent=2), flush=True)


def main():
    for spec in PROFILES:
        if spec["txt"].exists() or spec["json"].exists():
            raise RuntimeError(f"Result exists; refusing to overwrite: {spec['profile']}")
    if not AUDIO.is_file():
        raise FileNotFoundError(AUDIO)
    if ctranslate2.get_cuda_device_count() < 1:
        raise RuntimeError("CTranslate2 cannot see CUDA; CPU fallback is forbidden")

    audio_duration = float(command(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(AUDIO),
    ))
    load_started = time.perf_counter()
    model = WhisperModel(
        "large-v3", device="cuda", compute_type="float16", download_root=str(MODEL_ROOT)
    )
    model_load_seconds = time.perf_counter() - load_started
    idle_snapshot = gpu_snapshot()
    print(json.dumps({
        "model_load_seconds_shared": round(model_load_seconds, 3),
        "gpu_after_load": idle_snapshot,
    }, ensure_ascii=False), flush=True)
    for spec in PROFILES:
        run_profile(model, spec, audio_duration, model_load_seconds, idle_snapshot)


if __name__ == "__main__":
    main()
