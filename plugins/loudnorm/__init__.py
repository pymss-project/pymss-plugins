"""pymss plugin: LUFS loudness normalization.

Registers the `lufs_normalize` capability and a `NormalizeLUFS` workflow node.
Target loudness is set in LUFS (default -14, the streaming-platform standard).
"""

from __future__ import annotations

import numpy as np

from pymss.plugins import register_capability, register_node


def lufs_normalize(audio, sample_rate, target_lufs: float = -14.0):
    """Normalize audio to a target integrated loudness in LUFS.

    Uses pyloudnorm (declared as this plugin's dependency). Audio is channel-first
    (channels, samples) or 1-D mono, float32. Returns audio at the same layout
    scaled to reach the target loudness.
    """
    import pyloudnorm as pyln

    audio = np.asarray(audio, dtype=np.float32)
    meter = pyln.Meter(int(sample_rate))
    # pyloudnorm expects (channels, samples) float; mono needs 2-D.
    measure = audio if audio.ndim == 2 else audio[None, :]
    loudness = meter.integrated_loudness(measure)
    if not np.isfinite(loudness):
        # All-silent or degenerate input; return unchanged.
        return audio
    normalized = pyln.normalize.loudness(measure, loudness, target_lufs)
    return normalized[0] if audio.ndim == 1 else normalized


register_capability(
    "lufs_normalize",
    lufs_normalize,
    source="loudnorm",
    description="LUFS-based loudness normalization (broadcast/streaming standard)",
)


# Workflow node consuming the capability.
def _normalize_lufs_signature(node):
    from pymss.graph.core import NodeSignature, PortSpec, AUDIO

    return NodeSignature(
        inputs=[
            PortSpec(name="audio", type=AUDIO),
            PortSpec(name="target_lufs", type="FLOAT"),
        ],
        output_names=["audio"],
        output_types=[AUDIO],
    )


def _execute_normalize_lufs(ctx, inputs):
    from pymss.graph.core import AudioArtifact, DAGError, NodeResult, audio_to_numpy, numpy_to_audio

    audio_in = inputs.get("audio")
    if audio_in is None:
        raise DAGError("NormalizeLUFS requires an AUDIO input")
    waveform, sr = audio_to_numpy(audio_in)
    node = ctx.nodes_by_id[ctx.current_node_id]
    widgets = node.data.get("widgets_values", [])
    target = float(widgets[0]) if widgets else -14.0
    out = ctx.require("lufs_normalize")(waveform, sr, target_lufs=target)
    return NodeResult(outputs={0: numpy_to_audio(np.asarray(out, dtype=np.float32), sr)})


try:
    register_node(
        "NormalizeLUFS",
        _execute_normalize_lufs,
        signature=_normalize_lufs_signature,
        source="loudnorm",
    )
except Exception:
    # Node registration only works when the graph subsystem is present; the
    # capability above is still usable from the Python API / CLI without it.
    pass
