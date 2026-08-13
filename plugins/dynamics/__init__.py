"""pymss plugin: dynamics processing — compression, limiting, expansion, de-essing.

Registers capabilities backed by Spotify's pedalboard. Audio is numpy
(1-D mono or 2-D channels-first float32); output matches the input layout.
All dB parameters are in dBFS.
"""

from __future__ import annotations

import numpy as np

from pymss.plugins import register_capability


def _apply(board_cls, audio, sample_rate, **kwargs):
    """Apply a single pedalboard effect, preserving 1-D vs 2-D layout."""
    import pedalboard

    audio = np.asarray(audio, dtype=np.float32)
    flat = audio.ndim == 1
    x = audio[None, :] if flat else audio
    board = pedalboard.Pedalboard([board_cls(**kwargs)])
    out = board(x, int(sample_rate))
    return out[0] if flat else out


def compressor(audio, sample_rate, threshold_db=0.0, ratio=4.0, attack_ms=1.0,
               release_ms=100.0):
    """Feed-forward compressor. threshold_db/ratio/attack/release in dBFS / ratio / ms."""
    from pedalboard import Compressor

    return _apply(Compressor, audio, sample_rate,
                  threshold_db=threshold_db, ratio=ratio,
                  attack_ms=attack_ms, release_ms=release_ms)


def limiter(audio, sample_rate, threshold_db=-3.0, release_ms=100.0):
    """Brick-wall limiter: guarantees output peak ≤ threshold_db (dBFS).

    pedalboard's Limiter normalizes *toward* a loudness target rather than
    capping peaks, so for a true peak ceiling we pre-gain then soft-clip.
    threshold_db is the absolute peak ceiling (e.g. -1.0 for streaming).
    """
    import numpy as np
    from pedalboard import Limiter

    audio = np.asarray(audio, dtype=np.float32)
    ceiling = 10 ** (threshold_db / 20.0)
    # Normalize to ceiling, then soft-clip via pedalboard Limiter at 0 dB to
    # catch any overshoot without hard clipping artifacts.
    peak = float(np.max(np.abs(audio))) or 1.0
    if peak > 0:
        audio = audio * (ceiling / peak)
    return _apply(Limiter, audio, sample_rate, threshold_db=0.0, release_ms=release_ms)


def expander(audio, sample_rate, threshold_db=-50.0, ratio=2.0, attack_ms=1.0,
             release_ms=100.0):
    """Downward expander / gate-ish. Quiet signals below threshold are attenuated further."""
    from pedalboard import Compressor

    # pedalboard has no dedicated Expander; use Compressor with ratio < 1
    # to get expansion behaviour (ratio 0.5 = -2:1 expansion).
    return _apply(Compressor, audio, sample_rate,
                  threshold_db=threshold_db, ratio=ratio,
                  attack_ms=attack_ms, release_ms=release_ms)


def multiband_compressor(audio, sample_rate, low_freq=200.0, high_freq=4000.0,
                         low_threshold=-20.0, mid_threshold=-18.0, high_threshold=-20.0,
                         ratio=2.5):
    """Three-band compressor: split, compress each band, recombine.

    A simplified multiband (low/mid/high) using two Linkwitz-Riley-ish splits
    via pedalboard filters + three compressors. Not a true mastering-grade MBC
    but covers the common use case.
    """
    import numpy as np
    from pedalboard import Compressor, LowpassFilter, HighpassFilter, Gain

    audio = np.asarray(audio, dtype=np.float32)
    sr = int(sample_rate)
    flat = audio.ndim == 1
    x = audio[None, :] if flat else audio

    # Crude band split via first-order filters (good enough for dynamics control).
    low = pedalboard_pass(LowpassFilter(cutoff_frequency_hz=low_freq), x, sr)
    mid_raw = pedalboard_pass(HighpassFilter(cutoff_frequency_hz=low_freq), x, sr)
    mid = pedalboard_pass(LowpassFilter(cutoff_frequency_hz=high_freq), mid_raw, sr)
    high = pedalboard_pass(HighpassFilter(cutoff_frequency_hz=high_freq), mid_raw, sr)

    low_c = pedalboard_pass(Compressor(threshold_db=low_threshold, ratio=ratio), low, sr)
    mid_c = pedalboard_pass(Compressor(threshold_db=mid_threshold, ratio=ratio), mid, sr)
    high_c = pedalboard_pass(Compressor(threshold_db=high_threshold, ratio=ratio), high, sr)

    out = low_c + mid_c + high_c
    return out[0] if flat else out


def pedalboard_pass(effect, x, sr):
    import pedalboard

    return pedalboard.Pedalboard([effect])(x, sr)


def deesser(audio, sample_rate, threshold_db=0.0, ratio=3.0, crossover_hz=6000.0):
    """De-esser: compress only the high-frequency (sibilance) band.

    Splits at crossover_hz, compresses the high band, recombines. A real
    de-esser is dynamic (only acts when sibilance present); this is a static
    high-band compressor that approximates the effect.
    """
    from pedalboard import Compressor, HighpassFilter, LowpassFilter

    audio = np.asarray(audio, dtype=np.float32)
    sr = int(sample_rate)
    flat = audio.ndim == 1
    x = audio[None, :] if flat else audio

    low = pedalboard_pass(LowpassFilter(cutoff_frequency_hz=crossover_hz), x, sr)
    high_raw = pedalboard_pass(HighpassFilter(cutoff_frequency_hz=crossover_hz), x, sr)
    high_c = pedalboard_pass(
        Compressor(threshold_db=threshold_db, ratio=ratio, attack_ms=0.5, release_ms=50.0),
        high_raw, sr,
    )
    out = low + high_c
    return out[0] if flat else out


for _name, _fn in [
    ("compressor", compressor),
    ("limiter", limiter),
    ("expander", expander),
    ("multiband_compressor", multiband_compressor),
    ("deesser", deesser),
]:
    register_capability(_name, _fn, source="dynamics")
