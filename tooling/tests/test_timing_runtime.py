from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SCRIPT = Path(__file__).resolve().parents[2] / "plugins/timing/scripts/prepare_runtime.py"
spec = importlib.util.spec_from_file_location("timing_runtime", SCRIPT)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class TimingRuntimeTests(unittest.TestCase):
    def test_radius_checksum_failure_never_publishes_an_unverified_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "radius.exe"
            binary.write_bytes(b"incorrect native runtime")
            with self.assertRaisesRegex(ValueError, "SHA256"):
                runtime.prepare_radius("win32-x86_64", root / "bin", binary=binary)
            self.assertFalse((root / "bin/win32-x86_64/radius").exists())

    def test_engines_can_be_prepared_in_either_order_without_overwriting(self):
        filename, _, members = runtime.RELEASES["win32-x86_64"]
        for order in [("radius", "rubberband"), ("rubberband", "radius")]:
            with self.subTest(order=order), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive = root / "upstream.zip"
                with zipfile.ZipFile(archive, "w") as bundle:
                    for member in members:
                        bundle.writestr(filename.removesuffix(".zip") + "/" + member, member.encode())
                binary = root / "radius.exe"
                binary.write_bytes(b"verified radius fixture")
                rubber_release = (filename, hashlib.sha256(archive.read_bytes()).hexdigest(), members)
                with patch.dict(runtime.RELEASES, {"win32-x86_64": rubber_release}), \
                     patch.dict(runtime.RADIUS_RELEASES, {"win32-x86_64": ("radius.exe", hashlib.sha256(binary.read_bytes()).hexdigest())}), \
                     patch("urllib.request.urlopen") as network:
                    outputs = {}
                    previous = {}
                    for engine in order:
                        outputs[engine] = runtime.prepare_radius("win32-x86_64", root / "bin", binary=binary) if engine == "radius" else runtime.prepare("win32-x86_64", root / "bin", archive=archive)
                        for path, content in previous.items():
                            self.assertEqual(path.read_bytes(), content)
                        previous.update({p: p.read_bytes() for p in outputs[engine].iterdir() if p.is_file()})
                    for engine in order:
                        with self.assertRaisesRegex(ValueError, "already exists"):
                            if engine == "radius":
                                runtime.prepare_radius("win32-x86_64", root / "bin", binary=binary)
                            else:
                                runtime.prepare("win32-x86_64", root / "bin", archive=archive)
                    for path, content in previous.items():
                        self.assertEqual(path.read_bytes(), content)
                    network.assert_not_called()

    def test_radius_preparation_preserves_other_engine_and_copies_upstream_licenses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "bin/win32-x86_64"
            target.mkdir(parents=True)
            (target / "rubberband.exe").write_bytes(b"existing rubberband")
            binary = root / "radius.exe"
            binary.write_bytes(b"verified radius fixture")
            with patch("urllib.request.urlopen") as network, \
                 patch.dict(runtime.RADIUS_RELEASES, {"win32-x86_64": ("radius.exe", hashlib.sha256(binary.read_bytes()).hexdigest())}):
                output = runtime.prepare_radius("win32-x86_64", root / "bin", binary=binary)
            network.assert_not_called()
            self.assertEqual((output / "radius.exe").read_bytes(), binary.read_bytes())
            self.assertIn("GNU LESSER GENERAL PUBLIC LICENSE", (output / "LICENSE.radius").read_text(encoding="utf-8"))
            self.assertIn("GNU GENERAL PUBLIC LICENSE", (output / "COPYING.GPL3").read_text(encoding="utf-8"))
            self.assertEqual((target / "rubberband.exe").read_bytes(), b"existing rubberband")
            metadata = json.loads((output / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["sha256"], hashlib.sha256((output / "radius.exe").read_bytes()).hexdigest())
            self.assertEqual(metadata["license"], "LGPL-3.0-or-later")
            self.assertEqual(metadata["version"], "0.3.1")
            self.assertEqual(metadata["packageVersion"], "0.3.0")

    def test_shipped_engines_have_matching_platform_manifests_and_binary_hashes(self):
        package = SCRIPT.parents[1]
        for target in ["win32-x86_64", "darwin-arm64", "linux-x86_64"]:
            for engine in (["radius"] if target.startswith("linux-") else ["radius", "rubberband"]):
                with self.subTest(target=target, engine=engine):
                    directory = package / "bin" / target / engine
                    manifest = json.loads((directory / "runtime.json").read_text(encoding="utf-8"))
                    program = directory / (engine + (".exe" if target.startswith("win32-") else ""))
                    self.assertEqual(manifest["target"], target)
                    expected = manifest["sha256"] if engine == "radius" else manifest["binarySha256"]
                    self.assertEqual(hashlib.sha256(program.read_bytes()).hexdigest(), expected)
                    if engine == "radius":
                        self.assertEqual(manifest["sha256"], runtime.RADIUS_RELEASES[target][1])
                        self.assertEqual(manifest["version"], runtime.RADIUS_VERSION)
                        self.assertEqual(manifest["packageVersion"], runtime.RADIUS_PACKAGE_VERSION)
                        self.assertEqual(manifest["sourceCommit"], runtime.RADIUS_COMMIT)
                        if target.startswith("linux-"):
                            self.assertTrue(program.read_bytes().startswith(b"\x7fELF\x02\x01"))
                            self.assertEqual(manifest["requirements"]["glibc"], ">=2.34")
                    if target == "win32-x86_64" and engine == "rubberband":
                        self.assertTrue((directory / "sndfile.dll").is_file())

    def test_local_source_install_preserves_both_platforms_and_engine_payloads(self):
        from pymss.plugins.install import install

        package = SCRIPT.parents[1]
        with tempfile.TemporaryDirectory() as directory:
            result = install(str(package), plugins_dir=Path(directory), no_deps=True)
            self.assertEqual(result.name, "pymss.timing")
            expected = {p.relative_to(package): p.read_bytes() for p in (package / "bin").rglob("*") if p.is_file()}
            self.assertTrue(expected)
            for relative, content in expected.items():
                self.assertEqual((result.path / relative).read_bytes(), content, str(relative))

    def test_radius_requires_an_explicit_current_build_without_downloading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("urllib.request.urlopen") as network, self.assertRaisesRegex(ValueError, "current Radius build"):
                runtime.prepare_radius("win32-x86_64", root / "bin")
            network.assert_not_called()
            self.assertFalse((root / "bin").exists())

    def test_radius_rejects_empty_or_oversized_local_binaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "invalid.exe"
            for size in [0, 32 * 1024 * 1024 + 1]:
                with self.subTest(size=size):
                    with binary.open("wb") as stream:
                        stream.truncate(size)
                    with self.assertRaisesRegex(ValueError, "non-empty regular file"):
                        runtime.prepare_radius("win32-x86_64", root / "bin", binary=binary)
                    self.assertFalse((root / "bin").exists())

    def test_offline_preparation_keeps_runtime_dependency_and_license_files(self):
        filename, _, members = runtime.RELEASES["win32-x86_64"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "upstream.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                for member in members:
                    bundle.writestr(filename.removesuffix(".zip") + "/" + member, member.encode())
                bundle.writestr("../../outside.txt", b"must never extract")
            release = (filename, hashlib.sha256(archive.read_bytes()).hexdigest(), members)
            with patch.dict(runtime.RELEASES, {"win32-x86_64": release}), patch("urllib.request.urlopen") as network:
                output = runtime.prepare("win32-x86_64", root / "bin", archive=archive)
            network.assert_not_called()
            self.assertEqual((output / "sndfile.dll").read_bytes(), b"sndfile.dll")
            self.assertEqual((output / "COPYING.txt").read_bytes(), b"COPYING.txt")
            self.assertTrue((output / "runtime.json").is_file())
            self.assertTrue((output / "RUBBERBAND-NOTICE.md").is_file())
            self.assertFalse((root / "outside.txt").exists())
            self.assertEqual(list((root / "bin").iterdir()), [output.parent])
            self.assertEqual(list(output.parent.iterdir()), [output])

    def test_checksum_failure_never_publishes_partial_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "wrong.zip"
            archive.write_bytes(b"untrusted")
            with self.assertRaisesRegex(ValueError, "SHA256"):
                runtime.prepare("win32-x86_64", root / "bin", archive=archive)
            self.assertEqual(list((root / "bin").iterdir()), [])

    def test_existing_runtime_is_preserved_without_a_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installed = root / "win32-x86_64"
            installed.mkdir()
            (installed / "rubberband.exe").write_bytes(b"existing")
            with patch("urllib.request.urlopen") as network, self.assertRaisesRegex(ValueError, "already exists"):
                runtime.prepare("win32-x86_64", root)
            network.assert_not_called()
            self.assertEqual((installed / "rubberband.exe").read_bytes(), b"existing")

    def test_unavailable_platform_does_not_download_or_create_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bin"
            with patch("urllib.request.urlopen") as network, self.assertRaisesRegex(ValueError, "No pinned upstream binary"):
                runtime.prepare("linux-x86_64", output)
            network.assert_not_called()
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
