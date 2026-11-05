# Radius native runtime

The packaged engine is radius-rs release 0.3.1, maintained at:
https://github.com/SUC-DriverOld/radius-rs

Source revision: `696dba8acb900a87897e42e9b2d0ea4c4521bfb1`.
Corresponding upstream source archive:
https://github.com/SUC-DriverOld/radius-rs/archive/696dba8acb900a87897e42e9b2d0ea4c4521bfb1.tar.gz

The v0.3.1 source still declares Cargo package version 0.3.0, and its CLI
reports `radius 0.3.0`. The release asset SHA256 and source revision above
identify the packaged v0.3.1 fix; `packageVersion` records the upstream value.

The native program is licensed under LGPL-3.0-or-later, as declared in that
revision's Cargo.toml. The upstream LICENSE and the GPLv3 terms it incorporates
are included as `LICENSE.radius` and `COPYING.GPL3` beside each executable.
The Python adapter has its own MIT license. Earlier development notices about
MIT authorization do not describe the packaged 0.3.1 release's license.
Upstream derivation credits remain in the source repository README.

Windows x86_64, macOS arm64 and Linux x86_64 CLI releases are included under `bin/`.
The x86_64 builds require AVX and FMA. The official Linux v0.3.1 executable
has a highest strong GLIBC requirement of 2.34; the adapter requires glibc
2.34 or newer. Upstream builds and checks it on Ubuntu 22.04 (glibc 2.35).
Older glibc systems need an upstream build compiled against an older baseline;
`PYMSS_RADIUS` can select that compatible executable.
Each `runtime.json` records the release asset, SHA256, target and source revision.
The preparation script checks the pinned upstream SHA256 before publication.
Plugin installation copies these files; it does not build or download an engine.
`PYMSS_RADIUS` may explicitly select another compatible CLI executable.

The adapter sets `RADIUS_FFMPEG_IO=1` in the child environment so decoding,
encoding and probing use FFmpeg. `RADIUS_FFMPEG` selects that program when it is
not on PATH; setting its path alone does not select the FFmpeg backend.
Studio supplies its bundled FFmpeg through PATH. Standalone pymss callers must
provide FFmpeg on PATH or through `RADIUS_FFMPEG`.

This plugin selects Radius VC and accepts sample rates from 8000 to 192000 Hz,
matching the upstream engine. The input rate is preserved without implicit
resampling. Duration percentages are passed directly to `--tempo`: 50 halves the duration, 100 keeps
it, and 200 doubles it. Progress uses the CLI's `RADIUS_PROGRESS=1` counters.
No additional pitch, gain or duration correction is applied to Radius output.
The algorithm source remains maintained upstream.

The `radius` algorithm selects `--fft radix2`, the reference-compatible default.
`radius_rustfft` selects `--fft rustfft`, which trades reference-exact VC output
for processing speed. Both choices use the same `--mode vc` processing path.
The adapter always passes the selected FFT explicitly, so `RADIUS_FFT` in the
parent environment cannot override the choice.
