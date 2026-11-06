"""Supervise the pinned rba CLI without depending on Studio services."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil

from pymss.operations import OperationContext
from pymss.operations.command import current_target
from pymss.plugins.kit import ToolError, current_operation_context, require_file, run_native_process

MAX_DURATION_SECONDS = 30 * 60
MIN_BPM_DURATION_SECONDS = 30
TIMEOUT_SECONDS = 3600


def _check_glibc(program: Path):
    try:
        manifest = json.loads(program.with_name("runtime.json").read_text(encoding="utf-8"))
        minimum = re.fullmatch(r">=(\d+)\.(\d+)", manifest["requirements"]["glibc"])
        if minimum is None:
            raise ValueError("Invalid glibc requirement")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ToolError("TEMPO_KEY_RBA_RUNTIME_INVALID",
                        "The packaged rba runtime metadata is missing or invalid. Reinstall the BPM and key plugin.",
                        recoverable=True) from error
    required = ".".join(minimum.groups())
    confstr = getattr(os, "confstr", None)
    try:
        version = confstr("CS_GNU_LIBC_VERSION") if confstr else None
    except (OSError, ValueError):
        version = None
    current = re.fullmatch(r"glibc (\d+)\.(\d+)(?:\.\d+)?", version or "")
    if current is None:
        raise ToolError("TEMPO_KEY_RBA_GLIBC_UNAVAILABLE",
                        f"Packaged rba requires glibc {required} or newer, but its system version could not be determined. "
                        "Set PYMSS_RBA to a compatible rba executable.", extra={"requiredGlibc": required})
    if tuple(map(int, current.groups())) < tuple(map(int, minimum.groups())):
        detected = ".".join(current.groups())
        raise ToolError("TEMPO_KEY_RBA_GLIBC_UNSUPPORTED",
                        f"Packaged rba requires glibc {required} or newer; detected {detected}. "
                        "Set PYMSS_RBA to a compatible rba executable.",
                        extra={"requiredGlibc": required, "currentGlibc": detected})


def executable() -> Path:
    configured = os.environ.get("PYMSS_RBA")
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file() or (os.name != "nt" and not os.access(path, os.X_OK)):
            raise ToolError("TEMPO_KEY_RBA_MISSING", "PYMSS_RBA must name an executable rba program.")
        return path
    target = current_target()
    name = "rba.exe" if os.name == "nt" else "rba"
    program = Path(__file__).resolve().parents[1] / "bin" / target / "rba" / name
    if program.is_file():
        if os.name != "nt" and not os.access(program, os.X_OK):
            raise ToolError("TEMPO_KEY_RBA_MISSING", "The packaged rba runtime is not executable.")
        if target.startswith("linux-"):
            _check_glibc(program)
        return program
    found = shutil.which("rba")
    if found:
        return Path(found).resolve()
    raise ToolError("TEMPO_KEY_RBA_MISSING",
                    "rba is not installed for this platform. Set PYMSS_RBA to a compatible executable.")


def _duration_seconds(path: Path) -> float:
    # Read metadata only. Signal decoding remains entirely inside rba, using
    # Symphonia by default or its explicitly selected FFmpeg backend.
    import av

    try:
        with av.open(str(path), mode="r") as container:
            if not container.streams.audio:
                raise ValueError("No audio stream")
            stream = container.streams.audio[0]
            sample_rate = stream.codec_context.sample_rate
            if stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base)
            elif container.duration is not None:
                duration = float(container.duration / av.time_base)
            else:
                duration = None
    except (av.error.FFmpegError, OSError, ValueError, OverflowError) as error:
        raise ToolError("TEMPO_KEY_DURATION_UNKNOWN",
                        "The audio duration could not be determined. Convert the file to WAV or FLAC and retry.",
                        recoverable=True) from error
    if duration is None or not math.isfinite(duration) or duration < 0:
        raise ToolError("TEMPO_KEY_DURATION_UNKNOWN",
                        "The audio duration could not be determined. Convert the file to WAV or FLAC and retry.",
                        recoverable=True)
    # Extreme rates can make the native fixed-input FFT resampler allocate huge
    # buffers even when the file contains only a handful of PCM samples.
    if not isinstance(sample_rate, int) or not 1000 <= sample_rate <= 768000:
        raise ToolError("TEMPO_KEY_UNSUPPORTED_SAMPLE_RATE",
                        "The input sample rate is unsupported. Convert the audio to a standard-rate WAV and retry.",
                        recoverable=True)
    return duration


def _check_duration(duration: float):
    if duration > MAX_DURATION_SECONDS + 1e-6:
        raise ToolError("TEMPO_KEY_DURATION_LIMIT", "Each audio file supports at most 30 minutes of analysis.",
                        recoverable=True)


def _check_bpm_duration(duration: float):
    # Upstream's sub-30-second prior is derived from duration, not the beat.
    if duration + 1e-6 < MIN_BPM_DURATION_SECONDS:
        raise ToolError("TEMPO_KEY_TOO_SHORT",
                        "Automatic BPM detection requires at least 30 seconds of audio. Enter the BPM manually for shorter clips.",
                        recoverable=True)


def _validate_sample_rate(environment: dict[str, str]):
    value = environment.get("RBA_SAMPLE_RATE", environment.get("rba_sample_rate", "44100"))
    try:
        if re.fullmatch(r"\+?[0-9]+", value) is None:
            raise ValueError("Invalid sample rate")
        rate = int(value)
        if rate != 0 and not 8000 <= rate <= 192000:
            raise ValueError("Sample rate outside supported range")
    except ValueError as error:
        raise ToolError("TEMPO_KEY_INVALID_SAMPLE_RATE",
                        "RBA_SAMPLE_RATE must be 0 (default) or an integer from 8000 to 192000 Hz.",
                        recoverable=True) from error


def parse_report(stdout: str, stderr: str, *, bpm_only: bool) -> dict:
    fields = stdout.rstrip("\r\n").rsplit("\t", 1 if bpm_only else 2)
    bpm_field = fields[-1] if bpm_only else fields[-2] if len(fields) >= 2 else ""
    bpm_match = re.fullmatch(r"BPM: ([+-]?\d+(?:\.\d+)?)", bpm_field)
    samples = re.findall(r"(?m)^  samples\s*:\s*(\d+) \([^\r\n]*?@ (\d+) Hz\)\r?$", stderr)
    if len(fields) != (2 if bpm_only else 3) or bpm_match is None or len(samples) != 1:
        raise ToolError("TEMPO_KEY_INVALID_OUTPUT", "rba returned an invalid analysis report.")
    count, rate = map(int, samples[0])
    bpm = float(bpm_match[1])
    if not math.isfinite(bpm) or bpm < 0 or count <= 0 or rate <= 0:
        raise ToolError("TEMPO_KEY_INVALID_OUTPUT", "rba returned invalid tempo or duration values.")
    report = {"bpm": bpm, "duration": count / rate}
    if not bpm_only:
        key_match = re.fullmatch(r"KEY: (silence|[A-G](?:b|#)? (?:major|minor))", fields[-1])
        if key_match is None:
            raise ToolError("TEMPO_KEY_INVALID_OUTPUT", "rba returned an invalid musical key.")
        report["key"] = key_match[1]
    _check_duration(report["duration"])
    return report


def analyze_file(value, *, bpm_only: bool = False, context=None) -> dict:
    context = context or current_operation_context() or OperationContext()
    context.check_cancelled()
    path = require_file(value, "Input audio")
    program = executable()
    environment = dict(os.environ)
    _validate_sample_rate(environment)
    duration = _duration_seconds(path)
    _check_duration(duration)
    context.check_cancelled()
    arguments = [str(program), *(["--bpmonly"] if bpm_only else []), "--", str(path)]
    result = run_native_process(arguments, cwd=path.parent, context=context,
                                timeout=TIMEOUT_SECONDS, output_limit=65536, environment=environment)
    context.check_cancelled()
    report = parse_report(result.stdout, result.stderr, bpm_only=bpm_only)
    if bpm_only:
        _check_bpm_duration(report["duration"])
        onsets = re.findall(r"(?m)^  onsets \(slope\)\s*:\s*(\d+)\r?$", result.stderr)
        if len(onsets) != 1:
            raise ToolError("TEMPO_KEY_INVALID_OUTPUT", "rba returned invalid rhythmic-onset diagnostics.")
        # Upstream's short-clip prior can report a positive BPM even for silence.
        # Require enough onsets to infer an interval before replacing a manual BPM.
        if report["bpm"] <= 0 or int(onsets[0]) < 2:
            raise ToolError("TEMPO_KEY_NO_BPM", "No rhythmic onsets were detected. Enter the BPM manually.",
                            recoverable=True)
        report["roundedBpm"] = math.floor(report["bpm"] + 0.5)
    return report
