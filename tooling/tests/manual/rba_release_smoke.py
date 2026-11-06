"""Release gate for the actual packaged rba decoder, with reproducible media."""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import wave

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, help="Test a candidate executable instead of the packaged binary")
    parser.add_argument("--artifacts", type=Path, help="New directory for generated media and JSON results")
    args = parser.parse_args()
    artifacts = args.artifacts or Path(tempfile.mkdtemp(prefix="pymss-rba-release-"))
    if args.artifacts:
        artifacts.mkdir(parents=True, exist_ok=False)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        parser.error("FFmpeg is required to generate fixtures and independently verify decoded samples")
    for key in list(os.environ):
        if key.upper() in {"RBA_USE_FFMPEG", "RBA_FFMPEG", "RBA_SAMPLE_RATE", "PYMSS_RBA"}:
            del os.environ[key]
    if args.binary:
        os.environ["PYMSS_RBA"] = str(args.binary.resolve())
    from plugins.tempo_key.backend import rba
    rba.TIMEOUT_SECONDS = 15

    source = artifacts / "reference.wav"
    rate = 44100
    samples = array.array("h", (
        int(32767 * (.45 * math.sin(2 * math.pi * 440 * i / rate) * math.exp(-((i / rate) % .5) * 40)
                     + .25 * math.sin(2 * math.pi * 100 * i / rate) * math.exp(-((i / rate) % .5) * 25)))
        for i in range(rate * 12)
    ))
    if sys.byteorder != "little":
        samples.byteswap()
    with wave.open(str(source), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(samples.tobytes())

    def command(arguments):
        subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-y", *arguments], check=True,
                       capture_output=True, timeout=20)

    no_xing = artifacts / "valid-vbr-without-xing.mp3"
    indexed = artifacts / "indexed.mp3"
    command(["-i", str(source), "-c:a", "libmp3lame", "-q:a", "2", "-write_xing", "0", str(no_xing)])
    command(["-i", str(source), "-c:a", "libmp3lame", "-b:a", "192k", str(indexed)])
    pcm = artifacts / "independent-reference.f32"
    command(["-i", str(no_xing), "-map", "0:a:0", "-ac", "1", "-ar", str(rate), "-f", "f32le", str(pcm)])
    reference_duration = pcm.stat().st_size / 4 / rate
    rows = []
    before = hashlib.sha256(no_xing.read_bytes()).hexdigest()
    try:
        report = rba.analyze_file(no_xing)
        rows.append({"case": "complete-vbr-without-xing", "passed": abs(report["duration"] - reference_duration) <= .05,
                     "referenceDuration": reference_duration, "report": report})
    except Exception as error:
        rows.append({"case": "complete-vbr-without-xing", "passed": False, "error": str(error)})
    rows.append({"case": "source-unchanged", "passed": hashlib.sha256(no_xing.read_bytes()).hexdigest() == before})
    data = indexed.read_bytes()
    for name, content in [("truncated", data[:len(data) // 2]),
                          ("damaged-middle", data[:len(data) // 3] + bytes(len(data) // 3) + data[(len(data) // 3) * 2:])]:
        path = artifacts / (name + ".mp3")
        path.write_bytes(content)
        try:
            report = rba.analyze_file(path)
            rows.append({"case": name, "passed": False, "unexpectedSuccess": report})
        except Exception as error:
            rows.append({"case": name, "passed": True, "code": getattr(error, "code", type(error).__name__)})
    program = rba.executable()
    result = {"binary": str(program), "sha256": hashlib.sha256(program.read_bytes()).hexdigest(),
              "ffmpeg": ffmpeg, "cases": rows, "passed": all(row["passed"] for row in rows)}
    target = artifacts / "results.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "results": str(target),
                      "failed": [row["case"] for row in rows if not row["passed"]]}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
