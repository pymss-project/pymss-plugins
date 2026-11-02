"""pymss plugin: time-stretch and pitch-shift.

Registers pitch and speed processing with Radius or Rubber Band R3.
Both accept numpy audio (1-D mono or 2-D
channels-first float32) and return audio at the same layout.
"""

from __future__ import annotations

import numpy as np

from pymss.plugins.kit import operation_context

from .rubberband import pitch_shift as _rubberband_pitch_shift, time_stretch, _number


def pitch_shift(audio, sample_rate, n_steps: float, bins_per_octave: int = 12, algorithm: str = "rubberband"):
    if algorithm == "rubberband":
        return _rubberband_pitch_shift(audio, sample_rate, n_steps, bins_per_octave)
    if algorithm == "radius":
        from .radius import pitch_shift as radius_pitch_shift

        return radius_pitch_shift(audio, sample_rate, n_steps, bins_per_octave)
    raise ValueError("algorithm must be rubberband or radius")


def process(audio, sample_rate, n_steps: float = 0, duration_percent: float = 100, algorithm: str = "rubberband"):
    steps = _number(n_steps, "n_steps", -24, 24)
    duration = _number(duration_percent, "duration_percent", 25, 400)
    if algorithm == "radius":
        from .radius import process as radius_process

        return radius_process(audio, sample_rate, steps, duration)
    if algorithm != "rubberband":
        raise ValueError("algorithm must be rubberband or radius")
    from .rubberband import process as rubberband_process

    return rubberband_process(audio, sample_rate, pitch=2 ** (steps / 12), rate=100 / duration)


def setup(plugin):
    """Register pitch_shift / time_stretch as capabilities and Operations."""
    from pymss.graph.core import audio_to_numpy, numpy_to_audio

    plugin.register_capability(
        "pitch_shift", pitch_shift,
        description="Pitch-shift by fractional semitones with Rubber Band R3 or Radius, preserving duration",
    )
    plugin.register_capability(
        "time_stretch", time_stretch,
        description="Time-stretch by rate without pitch change (Rubber Band R3)",
    )

    def _wrap(fn, extra_params):
        def run(ctx, inputs, params):
            audio_in = inputs["audio"]
            waveform, sr = audio_to_numpy(audio_in)
            with operation_context(ctx):
                out = fn(waveform, sr, **{k: v for k, v in params.items() if k in extra_params})
            return {"audio": numpy_to_audio(np.asarray(out, dtype=np.float32), sr,
                source_path=audio_in.source_path, stem_name=audio_in.stem_name, channel_layout=audio_in.channel_layout)}
        return run

    plugin.register_operation(
        id="pymss.timing.process",
        title="Pitch and Speed",
        description="Change pitch and output duration with Radius or Rubber Band R3",
        inputs={"audio": {"type": "audio"}},
        params={"type": "object", "properties": {
            "algorithm": {"type": "string", "default": "rubberband", "enum": ["rubberband", "radius"]},
            "n_steps": {"type": "number", "default": 0.0, "minimum": -24.0, "maximum": 24.0},
            "duration_percent": {"type": "number", "default": 100.0, "minimum": 25.0, "maximum": 400.0},
        }, "required": ["algorithm", "n_steps", "duration_percent"], "additionalProperties": False},
        outputs={"audio": {"type": "audio"}},
        run=_wrap(process, {"algorithm", "n_steps", "duration_percent"}),
    )
    plugin.register_operation(
        id="pymss.timing.pitch_shift",
        title="Pitch Shift",
        description="Shift pitch with Rubber Band R3 or Radius (duration preserved)",
        inputs={"audio": {"type": "audio"}},
        params={"type": "object", "properties": {
            "n_steps": {"type": "number", "default": 0.0, "minimum": -24.0, "maximum": 24.0},
            "bins_per_octave": {"type": "integer", "default": 12, "minimum": 1, "maximum": 36},
            "algorithm": {"type": "string", "default": "rubberband", "enum": ["rubberband", "radius"]},
        }, "additionalProperties": False},
        outputs={"audio": {"type": "audio"}},
        run=_wrap(pitch_shift, {"n_steps", "bins_per_octave", "algorithm"}),
    )
    plugin.register_operation(
        id="pymss.timing.time_stretch",
        title="Time Stretch",
        description="Time-stretch with Rubber Band R3 without pitch change",
        inputs={"audio": {"type": "audio"}},
        params={"type": "object", "properties": {
            "rate": {"type": "number", "default": 1.0, "minimum": 0.25, "maximum": 4.0},
        }, "additionalProperties": False},
        outputs={"audio": {"type": "audio"}},
        run=_wrap(time_stretch, {"rate"}),
    )

    _register_graph_nodes(plugin)


def _make_processor_node(capability_name, param_names, widget_defaults):
    """Build signature+execute pair for an audio->audio processor node."""
    from pymss.graph.core import AUDIO, NodeSignature, PortSpec

    defaults = dict(widget_defaults)

    def signature(node):
        return NodeSignature(
            inputs=[PortSpec(name="audio", type=AUDIO)],
            output_names=["audio"],
            output_types=[AUDIO],
        )

    def execute(ctx, inputs):
        from pymss.graph.core import DAGError, NodeResult, audio_to_numpy, numpy_to_audio

        audio_in = inputs.get("audio")
        if audio_in is None:
            raise DAGError(f"{capability_name} requires an AUDIO input")
        waveform, sr = audio_to_numpy(audio_in)
        node = ctx.nodes_by_id[ctx.current_node_id]
        widgets = node.data.get("widgets_values", [])
        kwargs = {}
        for index, name in enumerate(param_names):
            if index < len(widgets) and widgets[index] is not None:
                kwargs[name] = widgets[index]
            elif name in defaults:
                kwargs[name] = defaults[name]
        fn = ctx.require(capability_name)
        out = fn(waveform, sr, **kwargs)
        return NodeResult(outputs={0: numpy_to_audio(np.asarray(out, dtype=np.float32), sr,
            source_path=audio_in.source_path, stem_name=audio_in.stem_name, channel_layout=audio_in.channel_layout)})

    return signature, execute


def _register_graph_nodes(plugin):
    specs = [
        ('TimingPitchShift', 'pitch_shift', ['n_steps', 'bins_per_octave', 'algorithm'],
         {'n_steps': 0.0, 'bins_per_octave': 12, 'algorithm': 'rubberband'}),
        ('TimingTimeStretch', 'time_stretch', ['rate'],
         {'rate': 1.0}),
    ]
    for node_type, capability, parameters, defaults in specs:
        signature, execute = _make_processor_node(capability, parameters, defaults)
        plugin.register_node(node_type, execute, signature=signature)
