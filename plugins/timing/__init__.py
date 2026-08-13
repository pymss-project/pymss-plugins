"""pymss plugin: time-stretch and pitch-shift.

Registers `pitch_shift` and `time_stretch` capabilities, backed by librosa
(already a pymss dependency). Both accept numpy audio (1-D mono or 2-D
channels-first float32) and return audio at the same layout.
"""

from __future__ import annotations

import numpy as np

from pymss.plugins import register_capability


def pitch_shift(audio, sample_rate, n_steps: float, bins_per_octave: int = 12):
    """Shift pitch by `n_steps` semitones (fractional allowed).

    A positive `n_steps` raises pitch; negative lowers it. Duration is
    preserved (phase vocoder + resampling). Output keeps the input's
    channel layout.
    """
    import librosa

    audio = np.asarray(audio, dtype=np.float32)
    y = librosa.effects.pitch_shift(
        audio, sr=int(sample_rate), n_steps=float(n_steps),
        bins_per_octave=int(bins_per_octave),
    )
    return y.astype(np.float32)


def time_stretch(audio, sample_rate, rate: float):
    """Time-stretch audio by `rate` without changing pitch.

    `rate > 1` speeds up (shorter); `0 < rate < 1` slows down (longer).
    The returned length is round(len / rate). sample_rate is accepted for
    API symmetry but unused by librosa's phase vocoder.
    """
    import librosa

    audio = np.asarray(audio, dtype=np.float32)
    y = librosa.effects.time_stretch(audio, rate=float(rate))
    return y.astype(np.float32)


register_capability(
    "pitch_shift", pitch_shift, source="timing",
    description="Pitch-shift by fractional semitones (librosa, duration preserved)",
)
register_capability(
    "time_stretch", time_stretch, source="timing",
    description="Time-stretch by rate without pitch change (librosa phase vocoder)",
)
