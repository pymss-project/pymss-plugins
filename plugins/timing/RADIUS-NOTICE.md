# Radius external runtime

The optional pitch-shifting engine is radius-rs:
https://github.com/SUC-DriverOld/radius-rs

The adapter was tested against the Windows x86_64 executable from release
`v0.0.3`, SHA256
`485b6cae356729bd4e599d48fc0a38fc21dd2b4b52b047326d341d61a26eb09d`.
That release's `--version` reports `radius 0.1.0`; the release identifier and
checksum, rather than the internal version string alone, identify the tested
binary. The release also provides an Apple Silicon macOS executable.

The project maintainer confirmed MIT distribution authorization on 2026-11-01.
The authorized license is retained in `licenses/LICENSE.radius` and copied
alongside the prepared native executable. The v0.0.3 upstream source snapshot
did not yet contain a LICENSE file or Cargo license declaration; this notice
records the explicit authorization rather than inferring a license from source
availability. Upstream should retain the same license in future source releases.
Original derivation credits are retained in the radius-rs README, which identifies
the pyradius and libradius implementations by baicai-1145 as its references.

The preparation script explicitly downloads pinned native releases for local
packaging. Native binaries are ignored by Git and are never downloaded during
plugin discovery, installation or execution. `PYMSS_RADIUS` may instead select
a separately installed executable. Third-party dependencies, including FFmpeg,
retain their own licenses.

The documented x86_64 build requires AVX and FMA. Other platforms and hardware
require a compatible runtime. The tested executable delegates audio I/O to
FFmpeg, located on PATH or using the upstream `RADIUS_FFMPEG` variable.

This plugin exposes only Radius's `vc` pitch-shifting mode, which supports
44100 and 48000 Hz audio. Other sample rates are rejected explicitly; no hidden
resampling is performed. Its tempo remains
fixed at 100; time stretching uses Rubber Band. Quality depends on the material,
and no universal quality ranking is asserted by the adapter.

Validation observed a 48 kHz, 440 Hz pure tone shifted by -6 semitones yielding
a dominant frequency near 316.5 Hz (the ideal is about 311.13 Hz, a difference
of roughly 30 cents). The adapter's output matched the direct upstream CLI
sample for sample. This is an observed upstream limitation, not a correction
applied by this plugin; auditioning remains necessary for quality comparisons.
