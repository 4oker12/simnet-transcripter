import argparse
import json
import subprocess
import time
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "models"


def duration_seconds(path: Path) -> float:
    value = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
    ).strip()
    return float(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--language", choices=["auto", "uk", "ru"], default="auto")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    duration = duration_seconds(args.audio)
    model_started = time.perf_counter()
    model = WhisperModel(
        "large-v3",
        device="cuda",
        compute_type="float16",
        download_root=str(MODEL_DIR),
    )
    model_load_seconds = time.perf_counter() - model_started

    inference_started = time.perf_counter()
    segments_iter, info = model.transcribe(
        str(args.audio),
        language=None if args.language == "auto" else args.language,
        vad_filter=True,
        beam_size=5,
    )
    segments = [
        {
            "id": segment.id,
            "start": round(segment.start, 3),
            "end": round(segment.end, 3),
            "text": segment.text.strip(),
        }
        for segment in segments_iter
    ]
    processing = time.perf_counter() - inference_started
    result = {
        "ok": True,
        "model": "large-v3",
        "device": "cuda",
        "compute_type": "float16",
        "vad_filter": True,
        "language": info.language,
        "language_probability": round(info.language_probability, 6),
        "duration_seconds": round(duration, 3),
        "model_load_seconds": round(model_load_seconds, 3),
        "processing_seconds": round(processing, 3),
        "realtime_factor": round(processing / duration, 4),
        "text": " ".join(row["text"] for row in segments if row["text"]),
        "segments": segments,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
