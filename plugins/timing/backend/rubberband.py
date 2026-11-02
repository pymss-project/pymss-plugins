"""Offline Rubber Band R3 processing, independent of any graphical host."""
from __future__ import annotations

import math
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import tempfile

import numpy as np

from .progress import NativeProgress

_versions: dict[tuple, bool] = {}


def executable() -> Path:
    """Prefer an explicit executable, then the package runtime, then PATH."""
    configured = os.environ.get("PYMSS_RUBBERBAND")
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file() or (os.name != "nt" and not os.access(path, os.X_OK)):
            raise RuntimeError("PYMSS_RUBBERBAND must name an executable Rubber Band 3.0 or newer")
        return path
    machine = platform.machine().lower()
    target = f"{sys.platform}-" + {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    name = "rubberband.exe" if os.name == "nt" else "rubberband"
    root = Path(__file__).resolve().parents[1] / "bin" / target
    for packaged in (root / "rubberband" / name, root / name):
        if packaged.is_file():
            if os.name != "nt" and not os.access(packaged, os.X_OK):
                raise RuntimeError("The packaged Rubber Band runtime is not executable")
            return packaged
    found = shutil.which("rubberband") or shutil.which("rubberband-r3")
    if found:
        return Path(found).resolve()
    raise RuntimeError(
        "Rubber Band 3.0 or newer is required. Install a prepared timing plugin, "
        "install rubberband on PATH, or set PYMSS_RUBBERBAND to its executable."
    )


def _number(value, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a finite number between {minimum} and {maximum}")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{label} must be a finite number") from error
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return number


def _run(arguments, *, label="Rubber Band R3", **kwargs):
    from pymss.plugins.kit import ToolError, run_native_process

    try:
        return run_native_process(arguments, **kwargs)
    except ToolError as error:
        detail = str(error.extra.get("stderr", "")).strip()
        raise ToolError(error.code, f"{label} failed: {detail or str(error)}",
                        recoverable=error.recoverable, extra=error.extra) from error


def _require_version(program: Path, context):
    from pymss.plugins.kit import ToolError

    info = program.stat()
    key = (program, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)
    if key in _versions:
        return
    version = _run([str(program), "--version"], cwd=program.parent, context=context, timeout=15, output_limit=4096)
    match = re.search(r"\b(\d+)\.\d+(?:\.\d+)?\b", version.stdout + "\n" + version.stderr)
    if match is None or int(match[1]) < 3:
        raise ToolError("TIMING_RUNTIME_UNSUPPORTED", "Rubber Band 3.0 or newer is required for the R3 engine")
    if len(_versions) >= 8:
        _versions.pop(next(iter(_versions)), None)
    _versions[key] = True


def _audio(audio, sample_rate):
    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim not in (1, 2) or samples.size == 0 or not np.isfinite(samples).all():
        raise ValueError("Audio must contain finite, non-empty mono or channels-first samples")
    sr = _number(sample_rate, "sample_rate", 1, 384000)
    if not sr.is_integer():
        raise ValueError("sample_rate must be an integer")
    return samples, int(sr)


def process(audio, sample_rate, *, pitch: float = 1.0, rate: float = 1.0):
    """Process current samples in scratch storage; never reread source_path."""
    import soundfile as sf
    from pymss.operations import OperationContext
    from pymss.plugins.kit import current_operation_context

    samples, sr = _audio(audio, sample_rate)
    pitch = _number(pitch, "pitch ratio", 1 / 16, 16)
    rate = _number(rate, "rate", 0.25, 4)
    context = current_operation_context() or OperationContext()
    context.check_cancelled()
    if pitch == 1 and rate == 1:
        return samples.copy()
    # Give very short clips analysis context instead of accepting an empty R3
    # render. Reflection keeps boundaries continuous; trim this context below.
    input_frames = samples.shape[-1]
    minimum_frames = max(2048, round(sr * 0.05))
    extra_frames = max(0, minimum_frames - input_frames)
    leading_frames = extra_frames // 2
    processing = samples
    if extra_frames:
        padding = (leading_frames, extra_frames - leading_frames)
        processing = np.pad(samples, (padding,) if samples.ndim == 1 else ((0, 0), padding),
                            mode="reflect" if input_frames > 1 else "edge")
    program = executable()
    # R3 was introduced in 3.0. Older system packages must fail explicitly.
    _require_version(program, context)
    with tempfile.TemporaryDirectory(prefix="pymss-rubberband-", dir=os.environ.get("PYMSS_SCRATCH_DIR") or None) as directory:
        work = Path(directory)
        source, output = work / "input.wav", work / "output.wav"
        context.report_progress(0.05, "Processing with Rubber Band R3")
        # The upstream CLI clamps even FLOAT output under --ignore-clipping.
        # Reserve headroom and restore gain after reading; retry if still clipped.
        scale = max(1.0, float(np.abs(samples).max()) * 8)
        progress = NativeProgress(context, "rubberband")
        for attempt in range(4):
            context.check_cancelled()
            sf.write(source, processing.T / scale, int(sr), subtype="FLOAT")
            _run(
                [str(program), "--fine", "--no-threads", "--ignore-clipping",
                 *(["--centre-focus"] if samples.ndim == 2 and samples.shape[0] > 1 else []),
                 "--frequency", format(pitch, ".17g"), "--tempo", format(rate, ".17g"),
                 source.name, output.name],
                cwd=work, context=context, timeout=21600, output_limit=65536, output_callback=progress,
            )
            context.check_cancelled()
            result, actual_rate = sf.read(output, dtype="float32", always_2d=True)
            expected_channels = 1 if samples.ndim == 1 else samples.shape[0]
            if actual_rate != int(sr) or result.shape[1] != expected_channels or not result.size or not np.isfinite(result).all():
                raise RuntimeError("Rubber Band returned invalid audio, sample rate or channel count")
            if float(np.abs(result).max()) < 0.999:
                break
            scale *= 4
        else:
            raise RuntimeError("Rubber Band output exceeded its processing headroom")
        # A buffered ufunc avoids allocating a full float64 copy of long audio.
        with np.errstate(over="ignore", invalid="ignore"):
            np.multiply(result, scale, out=result, dtype=np.float64, casting="unsafe")
        if not np.isfinite(result).all():
            raise ValueError("Rubber Band output exceeds the finite float32 audio range")
        expected_frames = round(processing.shape[-1] / rate)
        if abs(result.shape[0] - expected_frames) > 1:
            raise RuntimeError("Rubber Band returned an unexpected audio duration")
        result = result[:expected_frames]
        if len(result) < expected_frames:
            result = np.pad(result, ((0, expected_frames - len(result)), (0, 0)))
        start = round(leading_frames / rate)
        result = result[start:start + max(1, round(input_frames / rate))]
        context.report_progress(1.0, "Rubber Band processing completed")
        return np.ascontiguousarray(result[:, 0] if samples.ndim == 1 else result.T)


def pitch_shift(audio, sample_rate, n_steps: float, bins_per_octave: int = 12):
    steps = _number(n_steps, "n_steps", -24, 24)
    bins = _number(bins_per_octave, "bins_per_octave", 1, 36)
    if not bins.is_integer():
        raise ValueError("bins_per_octave must be an integer")
    return process(audio, sample_rate, pitch=2 ** (steps / bins))


def time_stretch(audio, sample_rate, rate: float):
    return process(audio, sample_rate, rate=rate)
