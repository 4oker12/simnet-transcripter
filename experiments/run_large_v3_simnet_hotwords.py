import json
import os
import subprocess
import threading
import time
from pathlib import Path

import ctranslate2
from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "test_audio" / "test.mp3"
RESULTS = ROOT / "results"
TXT_PATH = RESULTS / "large-v3-simnet-hotwords.txt"
JSON_PATH = RESULTS / "large-v3-simnet-hotwords.json"
MODEL_ROOT = ROOT / "models"

HOTWORDS = (
    "SIMNET, Сімнет, PlayStation, PS4, PS5, NAT, NAT type, тип NAT, IPv4, IPv6, "
    "MAC, MAC address, MAC-адрес, Cudy, MikroTik, TP-Link, ONU, ONT, OLT, GPON, "
    "EPON, GEPON, Juniper, BRAS, VLAN, DHCP, PPPoE, Wi-Fi, Ethernet, IP, IP-адрес, "
    "статический IP, выделенный IP, білий IP, мегабит, гигабит, роутер, оптика"
)

PARAMETERS = {
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
    "hotwords": HOTWORDS,
}


def duration_seconds() -> float:
    return float(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(AUDIO),
            ],
            text=True,
        ).strip()
    )


def gpu_name() -> str:
    return subprocess.check_output(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        text=True,
    ).strip().splitlines()[0]


class GpuMonitor:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.max_utilization = 0
        self.max_memory_mib = 0
        self.samples = 0

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                value = subprocess.check_output(
                    [
                        "nvidia-smi",
                        "--query-gpu=utilization.gpu,memory.used",
                        "--format=csv,noheader,nounits",
                    ],
                    text=True,
                    timeout=10,
                ).strip().splitlines()[0]
                utilization, memory = (int(part.strip()) for part in value.split(","))
                self.max_utilization = max(self.max_utilization, utilization)
                self.max_memory_mib = max(self.max_memory_mib, memory)
                self.samples += 1
            except Exception:
                pass
            self.stop_event.wait(0.25)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=15)


def atomic_create(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(temporary, "x", encoding="utf-8") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    if TXT_PATH.exists() or JSON_PATH.exists():
        raise RuntimeError("Hotwords result already exists; refusing to overwrite")
    if ctranslate2.get_cuda_device_count() < 1:
        raise RuntimeError("CTranslate2 cannot see CUDA; CPU fallback is forbidden")

    audio_duration = duration_seconds()
    gpu = gpu_name()
    monitor = GpuMonitor()
    monitor.start()
    try:
        load_started = time.perf_counter()
        model = WhisperModel(
            "large-v3",
            device="cuda",
            compute_type="float16",
            download_root=str(MODEL_ROOT),
        )
        model_load_seconds = time.perf_counter() - load_started

        inference_started = time.perf_counter()
        segment_iter, info = model.transcribe(str(AUDIO), **PARAMETERS)
        segments = []
        text_parts = []
        for segment in segment_iter:
            clean_text = segment.text.strip()
            segments.append(
                {
                    "id": segment.id,
                    "seek": segment.seek,
                    "start": round(segment.start, 3),
                    "end": round(segment.end, 3),
                    "text": clean_text,
                    "avg_logprob": round(segment.avg_logprob, 6),
                    "compression_ratio": round(segment.compression_ratio, 6),
                    "no_speech_prob": round(segment.no_speech_prob, 6),
                }
            )
            if clean_text:
                text_parts.append(clean_text)
        processing_seconds = time.perf_counter() - inference_started
    finally:
        monitor.stop()

    full_text = " ".join(text_parts)
    payload = {
        "ok": True,
        "profile": "large-v3-simnet-hotwords",
        "model": "large-v3",
        "device": "cuda",
        "compute_type": "float16",
        "gpu": gpu,
        "ctranslate2_cuda_device_count": ctranslate2.get_cuda_device_count(),
        "language_setting": "auto",
        "detected_language": info.language,
        "language_probability": round(info.language_probability, 6),
        "transcribe_parameters": PARAMETERS,
        "audio_duration": round(audio_duration, 3),
        "duration_after_vad": round(info.duration_after_vad, 3),
        "model_load_seconds": round(model_load_seconds, 3),
        "processing_time": round(processing_seconds, 3),
        "realtime_factor": round(processing_seconds / audio_duration, 4),
        "segment_count": len(segments),
        "gpu_peak_utilization_percent": monitor.max_utilization,
        "gpu_peak_memory_mib_total": monitor.max_memory_mib,
        "gpu_monitor_samples": monitor.samples,
        "text": full_text,
        "segments": segments,
    }
    atomic_create(TXT_PATH, full_text + "\n")
    atomic_create(JSON_PATH, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: payload[key] for key in (
        "profile", "model", "device", "compute_type", "gpu", "detected_language",
        "language_probability", "audio_duration", "processing_time", "realtime_factor",
        "segment_count", "gpu_peak_utilization_percent", "gpu_peak_memory_mib_total",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
