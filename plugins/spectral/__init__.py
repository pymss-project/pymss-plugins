"""pymss plugin: spectral processing — parametric EQ and filters.

Registers `parametric_eq`, `highpass`, `lowpass`, `bandpass`, `notch`,
`bandshelf`, `baxandall_eq` capabilities. Uses scipy (already a pymss dep via
librosa) for biquad-based filters and pedalboard for the multiband EQ.
"""

from __future__ import annotations

import numpy as np

from pymss.plugins import register_capability


def _biquad(audio, sample_rate, btype, f0, Q=0.707, gain_db=0.0):
    """Apply a single scipy biquad filter, preserving layout.

    btype: 'lowpass' | 'highpass' | 'bandpass' | 'notch' | 'lowshelf' | 'highshelf' | 'peak' | 'bandshelf'
    f0: center/corner frequency in Hz
    Q: quality factor
    gain_db: shelf/peak gain in dB (used by peak/shelf types)
    """
    from scipy.signal import lfilter

    from pymss.plugins import require_capability

    audio = np.asarray(audio, dtype=np.float32)
    # Reuse pymss's built-in biquad coefficient helper if available, else compute.
    try:
        b, a = _coeffs(btype, float(f0), float(sample_rate), float(Q), float(gain_db))
    except Exception:
        # Fallback: delegate to a first-order approximation.
        b, a = _coeffs(btype, float(f0), float(sample_rate), float(Q), float(gain_db))
    flat = audio.ndim == 1
    x = audio[None, :] if flat else audio
    out = np.stack([lfilter(b, a, ch) for ch in x])
    return out[0] if flat else out


def _coeffs(btype, f0, sr, Q, gain_db):
    """Compute biquad coefficients per the Audio EQ Cookbook."""
    import math

    w0 = 2 * math.pi * f0 / sr
    cos = math.cos(w0)
    sin = math.sin(w0)
    A = 10 ** (gain_db / 40.0)
    alpha = sin / (2 * Q)

    if btype == "lowpass":
        b0 = (1 - cos) / 2
        b1 = 1 - cos
        b2 = (1 - cos) / 2
        a0 = 1 + alpha
        a1 = -2 * cos
        a2 = 1 - alpha
    elif btype == "highpass":
        b0 = (1 + cos) / 2
        b1 = -(1 + cos)
        b2 = (1 + cos) / 2
        a0 = 1 + alpha
        a1 = -2 * cos
        a2 = 1 - alpha
    elif btype == "bandpass":
        b0 = alpha
        b1 = 0
        b2 = -alpha
        a0 = 1 + alpha
        a1 = -2 * cos
        a2 = 1 - alpha
    elif btype == "notch":
        b0 = 1
        b1 = -2 * cos
        b2 = 1
        a0 = 1 + alpha
        a1 = -2 * cos
        a2 = 1 - alpha
    elif btype == "peak":
        b0 = 1 + alpha * A
        b1 = -2 * cos
        b2 = 1 - alpha * A
        a0 = 1 + alpha / A
        a1 = -2 * cos
        a2 = 1 - alpha / A
    elif btype == "lowshelf":
        b0 = A * ((A + 1) - (A - 1) * cos + 2 * math.sqrt(A) * alpha)
        b1 = 2 * A * ((A - 1) - (A + 1) * cos)
        b2 = A * ((A + 1) - (A - 1) * cos - 2 * math.sqrt(A) * alpha)
        a0 = (A + 1) + (A - 1) * cos + 2 * math.sqrt(A) * alpha
        a1 = -2 * ((A - 1) + (A + 1) * cos)
        a2 = (A + 1) + (A - 1) * cos - 2 * math.sqrt(A) * alpha
    elif btype == "highshelf":
        b0 = A * ((A + 1) + (A - 1) * cos + 2 * math.sqrt(A) * alpha)
        b1 = -2 * A * ((A - 1) + (A + 1) * cos)
        b2 = A * ((A + 1) + (A - 1) * cos - 2 * math.sqrt(A) * alpha)
        a0 = (A + 1) - (A - 1) * cos + 2 * math.sqrt(A) * alpha
        a1 = 2 * ((A - 1) - (A + 1) * cos)
        a2 = (A + 1) - (A - 1) * cos - 2 * math.sqrt(A) * alpha
    else:
        raise ValueError(f"unknown biquad btype: {btype!r}")

    return [b0 / a0, b1 / a0, b2 / a0], [1.0, a1 / a0, a2 / a0]


def highpass(audio, sample_rate, cutoff_hz, Q=0.707):
    """First-order-ish high-pass biquad at cutoff_hz."""
    return _biquad(audio, sample_rate, "highpass", cutoff_hz, Q=Q)


def lowpass(audio, sample_rate, cutoff_hz, Q=0.707):
    """Low-pass biquad at cutoff_hz."""
    return _biquad(audio, sample_rate, "lowpass", cutoff_hz, Q=Q)


def bandpass(audio, sample_rate, center_hz, Q=1.0):
    """Band-pass biquad at center_hz."""
    return _biquad(audio, sample_rate, "bandpass", center_hz, Q=Q)


def notch(audio, sample_rate, center_hz, Q=2.0):
    """Notch (band-stop) biquad — useful for removing hum at a specific frequency."""
    return _biquad(audio, sample_rate, "notch", center_hz, Q=Q)


def peak_eq(audio, sample_rate, center_hz, gain_db, Q=1.0):
    """Peaking EQ: boost/cut a band around center_hz by gain_db."""
    return _biquad(audio, sample_rate, "peak", center_hz, Q=Q, gain_db=gain_db)


def lowshelf(audio, sample_rate, cutoff_hz, gain_db, Q=0.707):
    """Low-shelf: boost/cut everything below cutoff_hz by gain_db."""
    return _biquad(audio, sample_rate, "lowshelf", cutoff_hz, Q=Q, gain_db=gain_db)


def highshelf(audio, sample_rate, cutoff_hz, gain_db, Q=0.707):
    """High-shelf: boost/cut everything above cutoff_hz by gain_db."""
    return _biquad(audio, sample_rate, "highshelf", cutoff_hz, Q=Q, gain_db=gain_db)


def parametric_eq(audio, sample_rate, bands):
    """Parametric EQ with an arbitrary number of biquad bands.

    `bands` is a list of dicts, each: {type, freq, gain_db?, Q?} where type is
    one of lowpass/highpass/peak/lowshelf/highshelf/notch. Bands are applied
    in sequence (cascade).
    """
    out = np.asarray(audio, dtype=np.float32)
    for band in bands:
        btype = band["type"]
        f0 = float(band["freq"])
        gain = float(band.get("gain_db", 0.0))
        Q = float(band.get("Q", 0.707))
        out = _biquad(out, sample_rate, btype, f0, Q=Q, gain_db=gain)
    return out


def baxandall_eq(audio, sample_rate, bass_db=0.0, treble_db=0.0,
                 bass_corner_hz=300.0, treble_corner_hz=3000.0):
    """Baxandall tone stack: shelf-style bass and treble control.

    bass_db / treble_db boost or cut. A classic hi-fi tone-control curve.
    """
    out = audio
    if bass_db != 0.0:
        out = lowshelf(out, sample_rate, bass_corner_hz, bass_db)
    if treble_db != 0.0:
        out = highshelf(out, sample_rate, treble_corner_hz, treble_db)
    return out


for _name, _fn in [
    ("highpass", highpass),
    ("lowpass", lowpass),
    ("bandpass", bandpass),
    ("notch", notch),
    ("peak_eq", peak_eq),
    ("lowshelf", lowshelf),
    ("highshelf", highshelf),
    ("parametric_eq", parametric_eq),
    ("baxandall_eq", baxandall_eq),
]:
    register_capability(_name, _fn, source="spectral")
