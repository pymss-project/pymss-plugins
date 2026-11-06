# Tempo and key

BPM and musical-key analysis with the packaged **rba 0.2.1** release.
Plugin ID: `pymss.tempo_key`; version: `0.3.0`.

Install from Studio's plugin marketplace or with `pymss install pymss.tempo_key`.
The plugin implements its own Operations and runs independently of Studio's
former native analysis service. Python requires `av>=14` for metadata checks;
signal decoding and analysis run inside the rba executable.

## Operations

| Operation | Input | Report |
|---|---|---|
| `pymss.tempo_key.analyze` | `audio` file | `bpm`, `key`, `duration` |
| `pymss.tempo_key.detect_bpm` | `audio` file | `bpm`, `roundedBpm`, `duration` |
| `pymss.tempo_key.tool` | `request` object containing `inputs` paths | Batch results, failures and progress |

```sh
pymss ops run pymss.tempo_key.analyze --input audio=/path/to/music.wav
pymss ops run pymss.tempo_key.detect_bpm --input audio=/path/to/vocals.wav
```

The BPM-only Operation passes `--bpmonly`, requires at least 30 seconds of audio
and at least two detected onsets before returning a tempo. Upstream applies a
duration-based prior below 30 seconds; it must not replace a manually entered
MIDI tempo. GAME's optional BPM detection uses that same Operation. GAME still
supports manually entered BPM when this plugin is missing or disabled.
Batch analysis retains per-file results and partial failures. Cancellation and
timeouts terminate the native process and its decoder descendants.

Each input supports at most 30 minutes. Metadata is checked before starting
the native process; files with unknown duration must first be converted to WAV
or FLAC. The reported duration comes from rba's decoded sample count. Source
audio is not modified. rba's estimates, especially for short clips, should be
checked against the source material.

## Native runtime

Windows x86_64, macOS arm64 and Linux x86_64 official binaries are packaged in
`bin/<platform>/rba/`. Linux requires glibc 2.35 or newer; macOS requires 11.0
or newer. Other platforms can use a compatible `rba` on PATH or specify its
executable with `PYMSS_RBA`. An invalid explicit override or incompatible
bundled program reports its error without silently selecting another engine.

The default decoder is built into rba and needs no external FFmpeg program.
To opt in to upstream's FFmpeg backend, set `RBA_USE_FFMPEG=1`; set `RBA_FFMPEG`
when FFmpeg is not on PATH. Setting only the executable path does not enable
that decoder. The adapter passes these environment settings to the child
without modifying the parent environment. rba also accepts the lowercase
aliases and its upstream `RBA_SAMPLE_RATE` analysis setting. The plugin accepts
0 (upstream default) or 8000–192000 Hz for that setting, rejecting extreme values
before starting the native program. Input rates from 1000 to 768000 Hz are
resampled by rba; malformed or extreme source rates are rejected before native
FFT allocation.

### Native decoder release gate

The packaged rba 0.2.1 release includes the upstream fixes for unindexed VBR
trimming, successful partial decoding of damaged indexed MP3 files, and lost
resampler tails. The release gate checks that valid VBR files are decoded in full
and truncated or corrupted indexed files fail. Metadata duration is not used as
an exact decoded-sample count because valid VBR metadata can be estimated.
FFmpeg remains an explicit opt-in; the plugin does not switch decoders silently.

Reproduce against the packaged binary or a candidate upstream fix:

```sh
python tooling/tests/manual/rba_release_smoke.py
python tooling/tests/manual/rba_release_smoke.py --binary /path/to/candidate-rba
```

This maintainer-only check requires FFmpeg to generate media and independently
verify native sample counts. It checks damaged inputs, preserves JSON evidence
and exits nonzero when any release condition fails. Normal plugin use does not
require an external FFmpeg executable.

Maintainers download the official assets and verify/stage each target with:

```sh
python plugins/tempo_key/scripts/prepare_runtime.py --target win32-x86_64 --binary /path/to/rba-0.2.1-windows-x64.exe
python plugins/tempo_key/scripts/prepare_runtime.py --target darwin-arm64 --binary /path/to/rba-0.2.1-macOS-arm64
python plugins/tempo_key/scripts/prepare_runtime.py --target linux-x86_64 --binary /path/to/rba-0.2.1-linux-x64
```

Existing destinations are preserved. Prepare updates under another `--output`
directory, verify them, then replace the runtime files and regenerate operation
metadata. Preserve Git executable mode `100755` for Linux/macOS executables.
The native GPL-3.0 license and corresponding source are documented in
[RBA-NOTICE.md](RBA-NOTICE.md).
