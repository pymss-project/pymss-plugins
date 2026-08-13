# loudnorm

LUFS-based loudness normalization plugin for pymss.

Provides the `lufs_normalize` capability and the `NormalizeLUFS` workflow node.

## Install

```sh
pymss install loudnorm
pip install pyloudnorm   # this plugin's dependency
```

## Use

Python API:

```python
from pymss.plugins import require_capability
out = require_capability("lufs_normalize")(audio, 44100, target_lufs=-14.0)
```

Workflow node: `NormalizeLUFS` with a `target_lufs` widget (default -14.0, the streaming-platform standard).

## Why LUFS

Peak normalization (pymss's built-in `normalize_peak`) only caps amplitude. LUFS measures *perceived* loudness, which is what broadcast (EBU R128) and streaming platforms (Spotify/Apple/YouTube) target. Use this when you need loudness consistency across tracks, not just anti-clipping.
