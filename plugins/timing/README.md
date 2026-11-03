# timing

Offline pitch shifting and time stretching with **Radius** or **Rubber Band R3**.
This replaces the librosa implementation while keeping plugin ID `pymss.timing`,
Operation IDs, capabilities and workflow node types compatible.

| Capability | Description |
|---|---|
| `pitch_shift` | Shift pitch by fractional semitones; duration preserved |
| `time_stretch` | Stretch by rate without changing pitch |

## Install

```sh
pymss install timing
```

Python dependencies are `numpy` and `soundfile`. Rubber Band processing requires
a Rubber Band executable **version 3.0 or newer**. It is resolved from
`PYMSS_RUBBERBAND` (an executable file path), `bin/<platform-arch>/rubberband/` in the plugin
(the earlier flat `bin/<platform-arch>/` layout remains supported),
then `rubberband` / `rubberband-r3` on PATH. An explicitly configured invalid
executable fails rather than silently selecting another installation.

Requires pymss 2.3.0 or newer, which provides
`pymss.plugins.kit.current_operation_context` and `run_native_process`. Plugin
setup also verifies these APIs before registering capabilities or operations,
including when only neutral transforms are requested.

## Packaged native programs

The repository includes Radius 0.2.0 and Rubber Band 4.0.0 CLI programs for
Windows x86_64 and macOS arm64. Catalog source installs include these files;
no compiler, separate Radius installation or native build workflow is required.
Windows also includes the upstream `sndfile.dll` dependency for Rubber Band.
The programs are located under `bin/<platform-arch>/<engine>/` with their
licenses and `runtime.json` provenance records. They remain outside the Studio
application bundle and are maintained with the plugin.

Radius always uses the FFmpeg I/O backend in this adapter. The child process
receives `RADIUS_FFMPEG_IO=1`; `RADIUS_FFMPEG` is an optional executable path.
Studio supplies FFmpeg through PATH. CLI users must provide FFmpeg through PATH
or that environment variable. Users do not need to set the I/O backend flag.

An explicit `PYMSS_RADIUS` or `PYMSS_RUBBERBAND` override takes precedence over
the packaged program. A missing or unusable selected engine reports its error
without substituting the other algorithm. Linux and macOS x86_64 users currently
need a compatible system runtime; no bundled Radius program is supplied there.
Downloaded macOS programs remain subject to the system's execution policy.

Maintainers update the upstream source and CLI release separately from this
repository. For each supported target, download the pinned Radius CLI and run:

```sh
python plugins/timing/scripts/prepare_runtime.py --target win32-x86_64 --radius-binary /path/to/radius-0.2.0-windows-x64.exe
python plugins/timing/scripts/prepare_runtime.py --target darwin-arm64 --radius-binary /path/to/radius-0.2.0-macOS-arm64
```

The script checks the Radius and Rubber Band release SHA256 values, preserves
existing destinations and records the copied bytes. `--archive` supplies a
previously downloaded Rubber Band archive; `--engine radius` or
`--engine rubberband` prepares one engine. To replace an existing release,
prepare into a separate `--output` directory, verify it, then replace the tracked
runtime files and update the plugin version and operation metadata. Preserve
Git executable mode `100755` on both macOS programs when committing from Windows.
Native files are marked `-text` in `.gitattributes` to preserve their bytes.

Radius 0.2.0 is LGPL-3.0-or-later; Rubber Band retains its upstream license.
Their licenses do not change the adapter's MIT license. See
[RADIUS-NOTICE.md](RADIUS-NOTICE.md) and [RUBBERBAND-NOTICE.md](RUBBERBAND-NOTICE.md)
for provenance, source locations and third-party distribution notices.

Radius uses a phase vocoder and Rubber Band uses its R3 engine. Processing
speed and the resulting sound depend on the source material.
Both engines support pitch and speed changes. The best result depends on the input; compare by
listening. Studio provides one algorithm selector, semitone control and duration
percentage control. Duration remains editable with either engine, and changing
algorithms preserves the current value. Both engines use the same meaning:
50% produces half the duration (faster), 100% preserves it, and 200% doubles it
(slower). Radius receives this value directly as `--tempo`; Rubber Band's
internal playback rate is `100 / duration_percent`. This changes no DSP code in radius-rs.
The workflow
pitch node appends the algorithm widget after its existing numeric controls,
so older graphs default to Rubber Band. The time-stretch node remains unchanged.

## Use

```python
from pymss.plugins import require_capability
out = require_capability("pitch_shift")(audio, 44100, n_steps=2)      # up a tone
out = require_capability("pitch_shift")(audio, 44100, n_steps=2, algorithm="radius")
out = require_capability("time_stretch")(audio, 44100, rate=1.5)      # 1.5x faster
```

The unified Operation is `pymss.timing.process`, with parameters `algorithm`,
`n_steps` and `duration_percent` (100 preserves the original duration). Older pitch-only and
time-only Operations remain available for existing integrations and graphs.

`audio` is mono `(samples,)` or channels-first `(channels, samples)`. The adapter
uses current samples, not the original file path, and retains float32 samples,
sample rate and channel order. Rubber Band runs R3 offline with channel coupling;
Radius runs its phase vocoder with independently specified pitch and tempo.
`rate > 1` shortens audio, and `rate < 1` lengthens it. Pitch ratio is
`2 ** (n_steps / bins_per_octave)`; supported ratios range from 1/16 to 16.
Float samples may exceed ±1; conversion to integer PCM is the exporter's choice.
For clips shorter than 50 ms (with a 2048-frame minimum analysis window), Rubber
Band receives reflected boundary context, which is trimmed after processing.
The returned duration follows the requested duration percentage. Radius rounds to the native
CLI's nearest output frame and rejects a duration that would produce no frames.
Neutral pitch and speed return an exact copy.

The native process is supervised for cancellation, timeout and descendant cleanup.
Operation cancellation removes its scratch files; standalone capability and graph
calls have the same timeout and process cleanup, with cancellation available when
the host provides it. Scratch directories honor `PYMSS_SCRATCH_DIR`.
Studio's existing optional page displays these same pymss Operations.

Progress is forwarded from native processing counters, not a timer: Radius's
final output-frame counter is enabled with `RADIUS_PROGRESS=1`; Rubber Band reports
its study and processing passes. The supervisor delivers bounded output callbacks
on the Operation's calling thread. Progress remains monotone, reserves completion
for successful output validation, and supports cancellation during processing.

See [RUBBERBAND-NOTICE.md](RUBBERBAND-NOTICE.md) for native licenses and distribution
requirements. Native package publication and cross-platform desktop acceptance
are separate from preparing the local runtime.
