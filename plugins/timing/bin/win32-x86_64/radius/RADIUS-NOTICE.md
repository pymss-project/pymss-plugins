# Radius native runtime

The packaged engine is radius-rs 0.2.0, maintained at:
https://github.com/SUC-DriverOld/radius-rs

Source revision: `c987c1a8d62b2ab46959483bb6e8abe04a8e2ace`.
Corresponding upstream source archive:
https://github.com/SUC-DriverOld/radius-rs/archive/c987c1a8d62b2ab46959483bb6e8abe04a8e2ace.tar.gz

The native program is licensed under LGPL-3.0-or-later, as declared in that
revision's Cargo.toml. The upstream LICENSE and the GPLv3 terms it incorporates
are included as `LICENSE.radius` and `COPYING.GPL3` beside each executable.
The Python adapter has its own MIT license. Earlier development notices about
MIT authorization do not describe the packaged 0.2.0 release's license.
Upstream derivation credits remain in the source repository README.

Windows x86_64 and macOS arm64 CLI releases are included under `bin/`.
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
