"""Offline pitch and speed processing with the Radius phase vocoder."""
from __future__ import annotations

import os
import math
import json
from pathlib import Path
import re
import shutil
import tempfile

import numpy as np

from pymss.operations.command import current_target

from .rubberband import _audio, _number, _run
from .progress import NativeProgress


def _check_bundled_glibc(program: Path):
    from pymss.plugins.kit import ToolError

    try:
        manifest = json.loads(program.with_name("runtime.json").read_text(encoding="utf-8"))
        requirement = manifest["requirements"]["glibc"]
        minimum = re.fullmatch(r">=(\d+)\.(\d+)", requirement)
        if minimum is None:
            raise ValueError("Invalid glibc requirement")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ToolError("TIMING_RADIUS_RUNTIME_INVALID",
                        "The bundled Radius runtime metadata is missing or invalid. Reinstall the timing plugin.",
                        recoverable=True) from error
    required = ".".join(minimum.groups())
    confstr = getattr(os, "confstr", None)
    try:
        version = confstr("CS_GNU_LIBC_VERSION") if confstr else None
    except (OSError, ValueError):
        version = None
    current = re.fullmatch(r"glibc (\d+)\.(\d+)(?:\.\d+)?", version or "")
    if current is None:
        raise ToolError("TIMING_RADIUS_GLIBC_UNAVAILABLE",
                        f"Bundled Radius requires glibc {required} or newer, but the system glibc version could not be determined. "
                        "Set PYMSS_RADIUS to a compatible Radius executable.",
                        extra={"requiredGlibc": required})
    detected = ".".join(current.groups())
    if tuple(map(int, current.groups())) < tuple(map(int, minimum.groups())):
        raise ToolError("TIMING_RADIUS_GLIBC_UNSUPPORTED",
                        f"Bundled Radius requires glibc {required} or newer; detected glibc {detected}. "
                        "Set PYMSS_RADIUS to a compatible Radius executable.",
                        extra={"requiredGlibc": required, "currentGlibc": detected})


def executable() -> Path:
    from pymss.plugins.kit import ToolError

    configured = os.environ.get("PYMSS_RADIUS")
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file() or (os.name != "nt" and not os.access(path, os.X_OK)):
            raise ToolError("TIMING_RADIUS_MISSING", "PYMSS_RADIUS must name an executable radius-rs program")
        return path
    target = current_target()
    root = Path(__file__).resolve().parents[1] / "bin" / target
    name = "radius.exe" if os.name == "nt" else "radius"
    for path in (root / "radius" / name, root / name):
        if path.is_file():
            if os.name != "nt" and not os.access(path, os.X_OK):
                raise ToolError("TIMING_RADIUS_MISSING", "The configured Radius runtime is not executable")
            if target.startswith("linux-") and path.parent == root / "radius":
                _check_bundled_glibc(path)
            return path
    found = shutil.which("radius")
    if found:
        return Path(found).resolve()
    raise ToolError("TIMING_RADIUS_MISSING", "Radius is not installed. Set PYMSS_RADIUS to a radius-rs executable or choose Rubber Band.")


def process(audio, sample_rate, n_steps: float = 0, duration_percent: float = 100, *, bins_per_octave: int = 12, fft: str = "radix2"):
    import soundfile as sf
    from pymss.operations import OperationContext
    from pymss.plugins.kit import ToolError, current_operation_context

    if fft not in {"radix2", "rustfft"}:
        raise ValueError("fft must be radix2 or rustfft")
    steps = _number(n_steps, "n_steps", -24, 24)
    duration = _number(duration_percent, "duration_percent", 25, 400)
    bins = _number(bins_per_octave, "bins_per_octave", 1, 36)
    if not bins.is_integer():
        raise ValueError("bins_per_octave must be an integer")
    semitones = _number(steps * 12 / bins, "Radius semitones", -48, 48)
    samples, sr = _audio(audio, sample_rate)
    context = current_operation_context() or OperationContext()
    context.check_cancelled()
    if semitones == 0 and duration == 100:
        return samples.copy()
    if not 8000 <= sr <= 192000:
        raise ToolError("TIMING_RADIUS_SAMPLE_RATE_UNSUPPORTED", "Radius VC supports sample rates from 8000 to 192000 Hz")
    # Match Radius's --tempo: 50 halves the duration, 200 doubles it.
    frames = math.floor(samples.shape[-1] * (duration / 100) + 0.5)
    if frames < 1:
        raise ValueError("The requested duration would produce an empty audio output")
    program = executable()
    with tempfile.TemporaryDirectory(prefix="pymss-radius-", dir=os.environ.get("PYMSS_SCRATCH_DIR") or None) as directory:
        work = Path(directory)
        sf.write(work / "input.wav", samples.T, sr, subtype="FLOAT")
        context.report_progress(0.05, f"Processing with Radius ({fft})")
        _run([str(program), "input.wav", "output.wav", "--mode", "vc", "--semitones", format(semitones, ".17g"),
              "--tempo", format(duration, ".17g"), "--fft", fft, "--bit-depth", "32f"],
             label="Radius", cwd=work, context=context, timeout=21600, output_limit=65536,
             output_callback=NativeProgress(context, "radius"),
             environment={**os.environ, "RADIUS_FFMPEG_IO": "1", "RADIUS_PROGRESS": "1", "RADIUS_COLOR": "0", "NO_COLOR": "1"})
        context.check_cancelled()
        output, rate = sf.read(work / "output.wav", dtype="float32", always_2d=True)
        channels = 1 if samples.ndim == 1 else samples.shape[0]
        if rate != sr or output.shape != (frames, channels) or not np.isfinite(output).all():
            raise RuntimeError("Radius returned invalid audio, sample rate, duration or channel count")
        context.report_progress(1.0, "Radius processing completed")
        return np.ascontiguousarray(output[:, 0] if samples.ndim == 1 else output.T)


def pitch_shift(audio, sample_rate, n_steps: float, bins_per_octave: int = 12, *, fft: str = "radix2"):
    return process(audio, sample_rate, n_steps, bins_per_octave=bins_per_octave, fft=fft)
