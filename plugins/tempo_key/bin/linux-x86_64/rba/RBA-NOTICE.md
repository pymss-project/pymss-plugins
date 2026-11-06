# rba native runtime

This plugin packages the official rba 0.2.1 release from:
https://github.com/SUC-DriverOld/rba/releases/tag/v0.2.1

Corresponding source revision: `631319291b85c25d130daa417b001136df0ea46b`.
Source archive:
https://github.com/SUC-DriverOld/rba/archive/631319291b85c25d130daa417b001136df0ea46b.tar.gz

The upstream Cargo package still reports `rba 0.2.0` with `--version`. The
release asset hashes and pinned source revision identify the 0.2.1 build.

The executable is licensed under `GPL-3.0`, as declared by the upstream
Cargo.toml. The complete upstream license is included as `LICENSE.rba` beside
every executable. The Python adapter retains its separate MIT license.

Upstream credits the MixMeister BPM Analyzer analysis-core rewrite and the
libKeyFinder port by Ibrahim Sha'ath. Corresponding source and derivation
credits remain available in the pinned upstream repository.

Windows x86_64, macOS arm64 and Linux x86_64 binaries are included. The Linux
binary's highest strong GLIBC dependency is 2.35. The macOS binary targets
macOS 11.0 or later. Each `runtime.json` identifies the asset, SHA256, source
revision and platform. The preparation script requires the pinned official
bytes; installation does not compile or download a native runtime.

rba decodes through its built-in Symphonia backend by default. Set
`RBA_USE_FFMPEG=1` to explicitly enable its external FFmpeg decoder and
`RBA_FFMPEG` to select that executable. Lowercase aliases are handled by rba.
The adapter does not enable FFmpeg, change channel mixing or correct the
reported BPM/key. `PYMSS_RBA` explicitly overrides the bundled executable.
