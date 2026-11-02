# Radius external runtime

The optional pitch and time-stretching engine is radius-rs:
https://github.com/SUC-DriverOld/radius-rs

This development cycle uses the current radius-rs source, including its native
tempo scheduling and the progress-counter fix. The adapter does not add version
gates between development snapshots. Supply the resulting binary explicitly;
the preparation script records the packaged bytes' SHA256 in `runtime.json`.
The old v0.0.3 release is not selected for this development build.

The project maintainer confirmed MIT distribution authorization on 2026-11-01.
The authorized license is retained in `licenses/LICENSE.radius` and copied
alongside the prepared native executable. The inspected upstream source
does not contain a LICENSE file or Cargo license declaration; this notice
records the explicit authorization rather than inferring a license from source
availability. Upstream should retain the same license in future source releases.
Original derivation credits are retained in the radius-rs README, which identifies
the pyradius and libradius implementations by baicai-1145 as its references.

The preparation script copies the developer-supplied current Radius build for
local packaging. Native binaries are ignored by Git and are never downloaded during
plugin discovery, installation or execution. `PYMSS_RADIUS` may instead select
a separately installed executable. Third-party dependencies, including FFmpeg,
retain their own licenses.

The executable must match the target architecture and CPU instruction set.
The tested executable delegates audio I/O to
FFmpeg, located on PATH or using the upstream `RADIUS_FFMPEG` variable.

This plugin uses Radius's `vc` mode and accepts 44100 and 48000 Hz audio.
Other sample rates are rejected explicitly; no hidden resampling is performed.
The unified operation supports pitch and speed together. Existing pitch-only
entry points keep tempo 100, preserving their duration contract.
Quality depends on the material,
and no universal quality ranking is asserted by the adapter.

Validation compares adapter output with the current native CLI sample for
sample. The adapter applies no pitch, gain or duration correction to the engine's
output; auditioning remains necessary for quality comparisons.
