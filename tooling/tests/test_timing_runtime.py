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

    def test_radius_preparation_preserves_other_engine_and_copies_mit_license(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "bin/win32-x86_64"
            target.mkdir(parents=True)
            (target / "rubberband.exe").write_bytes(b"existing rubberband")
            binary = root / "radius.exe"
            binary.write_bytes(b"verified radius fixture")
            with patch("urllib.request.urlopen") as network:
                output = runtime.prepare_radius("win32-x86_64", root / "bin", binary=binary)
            network.assert_not_called()
            self.assertEqual((output / "radius.exe").read_bytes(), binary.read_bytes())
            self.assertIn("MIT License", (output / "LICENSE.radius").read_text(encoding="utf-8"))
            self.assertEqual((target / "rubberband.exe").read_bytes(), b"existing rubberband")
            metadata = json.loads((output / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["sha256"], hashlib.sha256((output / "radius.exe").read_bytes()).hexdigest())

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
