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

The kernel must provide `pymss.plugins.kit.current_operation_context` and
`run_native_process`. The released pymss 2.2.0 does not include these APIs;
use the companion kernel update before loading this plugin. Plugin setup checks
these APIs before registering capabilities or operations, including when only
neutral transforms are requested. Development snapshots are checked by API
availability rather than by an intermediate version number.

For a source checkout, build the current radius-rs source and explicitly prepare
the native runtimes:

```sh
python plugins/timing/scripts/prepare_runtime.py --radius-binary /path/to/current/radius
```

The script prepares the pinned Rubber Band 4.0.0 release and the supplied Radius
build on Windows x86_64 and macOS arm64. Rubber Band downloads retain their pinned
SHA256 checks; the supplied Radius binary's SHA256 is recorded in `runtime.json`.
The old Radius v0.0.3 binary is not downloaded. The current source implements
tempo directly in the engine, replacing that release's postprocessing stage.
macOS x86_64 packaging currently supports Rubber Band only.
`--engine rubberband` or `--engine radius` prepares one engine explicitly.
Each engine is published to its own directory, so they can be prepared in either
order without replacing the other engine. Preparing an already present engine is
rejected before any download or overwrite.
`--archive <path>` permits preparation from a previously downloaded archive;
`--radius-binary <path>` uses the current source build supplied by the developer;
`--target` and `--output` support development packaging. No native program is
downloaded or built during plugin installation, discovery or processing.
Prepare the runtime **before installing this local directory** to include it
in the installed copy. Git source archives do not contain the ignored `bin/`
directory, so catalog source installs require a system runtime or explicit path.

On Linux, install your distribution's Rubber Band >=3.0 package or compile the
upstream command-line tool and place it on PATH. No Linux binary is claimed by
the preparation script. On macOS, downloaded executables remain subject to
Gatekeeper; follow the system's security prompts for the trusted upstream tool.
Prepared native binaries have not been signed or notarized by this project.

For Radius, supply the current [radius-rs source build](https://github.com/SUC-DriverOld/radius-rs)
using `PYMSS_RADIUS`, `bin/<platform-arch>/radius/radius[.exe]` or `radius` on PATH
(a directly placed `bin/<platform-arch>/radius[.exe]` is also accepted).
Build for the target architecture and instruction set. Audio I/O requires FFmpeg on PATH or via
`RADIUS_FFMPEG`. Radius's confirmed MIT authorization and derivation credits are
retained in [RADIUS-NOTICE.md](RADIUS-NOTICE.md) and `licenses/LICENSE.radius`.
An unavailable selected engine reports an error; it never silently substitutes
the other algorithm.

Radius's phase-vocoder mode prioritizes pitch-shifting quality for complex
material, at a higher processing cost. Rubber Band is the faster choice.
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
