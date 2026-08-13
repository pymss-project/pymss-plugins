# analysis

Read-only audio measurement. Capabilities return dicts, not audio.

| Capability | Returns |
|---|---|
| `measure_lufs` | Integrated loudness in LUFS |
| `measure_true_peak` | True peak in dBTP (4x oversampled) + sample peak |
| `measure_rms` | RMS in dBFS and linear |
| `measure_dynamic_range` | DR estimate (Lmax - Lmin over 400 ms blocks, in LU) |
| `spectrum_analyze` | Average power spectrum (freqs + magnitudes in dB) |

Install: `pymss install analysis` + `pip install pyloudnorm`.

## Use

```python
from pymss.plugins import require_capability
print(require_capability("measure_lufs")(audio, 44100))  # {'lufs': -14.3}
```
