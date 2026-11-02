"""Prepare native runtimes explicitly; never invoked by plugin installation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

VERSION = "4.0.0"
RELEASES = {
    "win32-x86_64": (
        "rubberband-4.0.0-gpl-executable-windows.zip",
        "f2d47fc64dbb42f6cc62edf7933ac4fa89d8f0ef8b9cf97b6afc263a7fe05644",
        {"rubberband.exe": "rubberband.exe", "sndfile.dll": "sndfile.dll",
         "COPYING.txt": "COPYING.txt", "README.txt": "README.txt", "CHANGELOG.txt": "CHANGELOG.txt"},
    ),
    "darwin": (
        "rubberband-4.0.0-gpl-executable-macos.tar.bz2",
        "0dc91509a31a94c1144436cc20e6f1d165bdab39fe125f9be7d46139921b733f",
        {"rubberband": "rubberband", "COPYING": "COPYING", "README.md": "README.md", "CHANGELOG": "CHANGELOG"},
    ),
}
RADIUS_TARGETS = {"win32-x86_64", "darwin-arm64"}


def prepare(target: str, output: Path, *, archive: Path | None = None) -> Path:
    release = RELEASES.get("darwin" if target.startswith("darwin-") else target)
    if target not in {"win32-x86_64", "darwin-x86_64", "darwin-arm64"} or release is None:
        raise ValueError("No pinned upstream binary for this target; use a system Rubber Band >=3.0 or build from upstream source")
    filename, checksum, members = release
    platform_root = output / target
    destination = platform_root / "rubberband"
    legacy_program = platform_root / ("rubberband.exe" if target.startswith("win32-") else "rubberband")
    if destination.exists() or legacy_program.is_file():
        raise ValueError(f"Runtime destination already exists: {destination}")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".rubberband-", dir=output) as temporary:
        scratch = Path(temporary)
        if archive is None:
            archive = scratch / filename
            with urllib.request.urlopen(f"https://breakfastquay.com/files/releases/{filename}", timeout=45) as response, archive.open("xb") as stream:
                size = 0
                while block := response.read(1024 * 1024):
                    size += len(block)
                    if size > 32 * 1024 * 1024:
                        raise ValueError("Rubber Band archive exceeds its download limit")
                    stream.write(block)
        if archive.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("Rubber Band archive exceeds its size limit")
        if hashlib.sha256(archive.read_bytes()).hexdigest() != checksum:
            raise ValueError("Rubber Band archive SHA256 does not match the pinned upstream release")
        stage = scratch / "runtime"
        stage.mkdir()
        prefix = filename.removesuffix(".zip").removesuffix(".tar.bz2") + "/"
        if filename.endswith(".zip"):
            with zipfile.ZipFile(archive) as bundle:
                for source, name in members.items():
                    content = bundle.read(prefix + source)
                    if len(content) > 16 * 1024 * 1024:
                        raise ValueError("Rubber Band runtime member exceeds its size limit")
                    (stage / name).write_bytes(content)
        else:
            with tarfile.open(archive, "r:bz2") as bundle:
                for source, name in members.items():
                    member = bundle.getmember(prefix + source)
                    if not member.isfile() or member.size > 16 * 1024 * 1024:
                        raise ValueError("Rubber Band runtime requires bounded regular files")
                    with bundle.extractfile(member) as stream:
                        (stage / name).write_bytes(stream.read())
        if not target.startswith("win32-"):
            (stage / "rubberband").chmod(0o755)
        (stage / "runtime.json").write_text(json.dumps({
            "version": VERSION, "target": target, "archive": filename, "sha256": checksum,
            "license": "GPL-2.0-or-later", "source": f"https://breakfastquay.com/files/releases/rubberband-{VERSION}.tar.bz2",
        }, indent=2) + "\n", encoding="utf-8")
        shutil.copyfile(Path(__file__).resolve().parents[1] / "RUBBERBAND-NOTICE.md", stage / "RUBBERBAND-NOTICE.md")
        # Atomic publication also rejects a concurrent preparation for the same target.
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.rename(stage, destination)
    return destination


def prepare_radius(target: str, output: Path, *, binary: Path | None = None) -> Path:
    if target not in RADIUS_TARGETS:
        raise ValueError("Radius packaging is not configured for this target; use a compatible system executable")
    destination = output / target / "radius"
    legacy_program = output / target / ("radius.exe" if target.startswith("win32-") else "radius")
    if destination.exists() or legacy_program.is_file():
        raise ValueError(f"Radius runtime destination already exists: {destination}")
    if binary is None:
        raise ValueError("Supply the current Radius build with --radius-binary")
    binary = binary.expanduser().resolve()
    if not binary.is_file() or not 0 < binary.stat().st_size <= 32 * 1024 * 1024:
        raise ValueError("Radius binary must be a non-empty regular file no larger than 32 MiB")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".radius-", dir=output) as temporary:
        scratch = Path(temporary)
        stage = scratch / "runtime"
        stage.mkdir()
        program = stage / ("radius.exe" if target.startswith("win32-") else "radius")
        shutil.copyfile(binary, program)
        if not target.startswith("win32-"):
            program.chmod(0o755)
        package = Path(__file__).resolve().parents[1]
        shutil.copyfile(package / "licenses/LICENSE.radius", stage / "LICENSE.radius")
        shutil.copyfile(package / "RADIUS-NOTICE.md", stage / "RADIUS-NOTICE.md")
        (stage / "runtime.json").write_text(json.dumps({
            "target": target, "asset": binary.name, "sha256": hashlib.sha256(program.read_bytes()).hexdigest(),
            "license": "MIT", "source": "https://github.com/SUC-DriverOld/radius-rs",
        }, indent=2) + "\n", encoding="utf-8")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.rename(stage, destination)
    return destination


def main(argv=None) -> int:
    machine = platform.machine().lower()
    target = f"{sys.platform}-" + {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=target)
    parser.add_argument("--engine", choices=["all", "rubberband", "radius"], default="all")
    parser.add_argument("--archive", type=Path, help="Use a previously downloaded official archive (SHA256 is still checked)")
    parser.add_argument("--radius-binary", type=Path, help="Use the current Radius source build; its SHA256 is recorded in runtime.json")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "bin")
    args = parser.parse_args(argv)
    if (args.engine == "radius" or args.engine == "all" and args.target in RADIUS_TARGETS) and args.radius_binary is None:
        parser.error("Supply the current Radius build with --radius-binary, or select --engine rubberband")
    try:
        output = args.output.resolve()
        if args.engine in {"all", "rubberband"}:
            print(prepare(args.target, output, archive=args.archive))
        if args.engine == "radius" or args.engine == "all" and args.target in RADIUS_TARGETS:
            print(prepare_radius(args.target, output, binary=args.radius_binary))
        elif args.engine == "all":
            print("Radius packaging is not configured for this target; only Rubber Band was prepared")
    except (OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Native runtime preparation failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
