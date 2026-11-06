"""Prepare a verified official rba release without downloading or compiling it."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile

VERSION = "0.2.1"
COMMIT = "631319291b85c25d130daa417b001136df0ea46b"
RELEASES = {
    "win32-x86_64": ("rba-0.2.1-windows-x64.exe", "becd5cc18c8f24cd185afb26765149272712c7ea55626ed74187f6d2cdeaf183"),
    "darwin-arm64": ("rba-0.2.1-macOS-arm64", "45dcd30064d022ea73939b13a0eb96a80489a787daf4b754134efbb558159b86"),
    "linux-x86_64": ("rba-0.2.1-linux-x64", "96c990fcca0ecfcbb5ecfbb70c8d72b9b9d73e12a00d6f563ffc13e5e45c7430"),
}


def prepare(target: str, output: Path, *, binary: Path) -> Path:
    if target not in RELEASES:
        raise ValueError("No pinned rba release for this platform; configure PYMSS_RBA instead.")
    destination = output / target / "rba"
    if destination.exists():
        raise ValueError(f"Runtime destination already exists: {destination}")
    binary = binary.expanduser().resolve()
    if not binary.is_file() or not 0 < binary.stat().st_size <= 32 * 1024 * 1024:
        raise ValueError("rba binary must be a non-empty regular file no larger than 32 MiB.")
    asset, checksum = RELEASES[target]
    if hashlib.sha256(binary.read_bytes()).hexdigest() != checksum:
        raise ValueError("rba binary SHA256 does not match the pinned official release.")
    output.mkdir(parents=True, exist_ok=True)
    package = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix=".rba-", dir=output) as temporary:
        stage = Path(temporary) / "runtime"
        stage.mkdir()
        program = stage / ("rba.exe" if target.startswith("win32-") else "rba")
        shutil.copyfile(binary, program)
        if not target.startswith("win32-"):
            program.chmod(0o755)
        shutil.copyfile(package / "licenses/LICENSE.rba", stage / "LICENSE.rba")
        shutil.copyfile(package / "RBA-NOTICE.md", stage / "RBA-NOTICE.md")
        (stage / "runtime.json").write_text(json.dumps({
            "version": VERSION, "target": target, "asset": asset, "sha256": checksum,
            "license": "GPL-3.0", "sourceCommit": COMMIT,
            "source": f"https://github.com/SUC-DriverOld/rba/tree/{COMMIT}",
            "sourceArchive": f"https://github.com/SUC-DriverOld/rba/archive/{COMMIT}.tar.gz",
            **({"requirements": {"glibc": ">=2.35"}} if target.startswith("linux-") else {}),
        }, indent=2) + "\n", encoding="utf-8", newline="\n")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.rename(stage, destination)
    return destination


def main(argv=None):
    machine = platform.machine().lower()
    target = f"{sys.platform}-" + {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=target)
    parser.add_argument("--binary", type=Path, required=True, help=f"Official rba {VERSION} executable; SHA256 is checked")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "bin")
    args = parser.parse_args(argv)
    try:
        print(prepare(args.target, args.output.resolve(), binary=args.binary))
        return 0
    except (OSError, ValueError) as error:
        print(f"rba runtime preparation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
