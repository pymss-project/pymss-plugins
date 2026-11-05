from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from plugins.timing.backend import radius
from pymss.plugins.kit import ToolError


class TimingRadiusCompatibilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.package = Path(temporary.name) / "timing"
        self.program = self.package / "bin/linux-x86_64/radius/radius"
        self.program.parent.mkdir(parents=True)
        self.program.write_bytes(b"native fixture; never executed")
        self.manifest = self.program.with_name("runtime.json")
        self.manifest.write_text(json.dumps({"requirements": {"glibc": ">=2.43"}}), encoding="utf-8")
        self.system = SimpleNamespace(name="posix", environ={}, X_OK=os.X_OK,
                                      access=Mock(return_value=True), confstr=Mock(return_value="glibc 2.42"))
        for name, value in [("os", self.system), ("__file__", str(self.package / "backend/radius.py")),
                            ("current_target", Mock(return_value="linux-x86_64"))]:
            active = patch.object(radius, name, value)
            active.start()
            self.addCleanup(active.stop)
        active = patch.object(radius.shutil, "which", return_value=str(self.package / "system-radius"))
        self.which = active.start()
        self.addCleanup(active.stop)

    def test_old_glibc_fails_before_launch_without_selecting_path(self):
        with patch.object(radius, "_run") as launch:
            for fft in ["radix2", "rustfft"]:
                with self.subTest(fft=fft):
                    with self.assertRaises(ToolError) as caught:
                        radius.process(np.ones(4096, dtype=np.float32), 8000, 3, fft=fft)
                    self.assertEqual(caught.exception.code, "TIMING_RADIUS_GLIBC_UNSUPPORTED")
                    self.assertEqual(caught.exception.extra, {"requiredGlibc": "2.43", "currentGlibc": "2.42"})
                    self.assertIn("PYMSS_RADIUS", str(caught.exception))
            launch.assert_not_called()
        self.which.assert_not_called()

    def test_version_comparison_is_numeric_and_accepts_equal_or_newer_glibc(self):
        for version in ["2.43", "2.43.1", "2.100", "3.0"]:
            with self.subTest(version=version):
                self.system.confstr.return_value = "glibc " + version
                self.assertEqual(radius.executable(), self.program)
        self.system.confstr.return_value = "glibc 2.9"
        with self.assertRaises(ToolError) as caught:
            radius.executable()
        self.assertEqual(caught.exception.code, "TIMING_RADIUS_GLIBC_UNSUPPORTED")
        self.which.assert_not_called()

    def test_minimum_glibc_is_read_from_the_selected_runtime_manifest(self):
        self.manifest.write_text(json.dumps({"requirements": {"glibc": ">=2.35"}}), encoding="utf-8")
        self.system.confstr.return_value = "glibc 2.35"
        self.assertEqual(radius.executable(), self.program)
        self.system.confstr.return_value = "glibc 2.34"
        with self.assertRaises(ToolError) as caught:
            radius.executable()
        self.assertEqual(caught.exception.extra["requiredGlibc"], "2.35")

    def test_unknown_or_non_glibc_system_has_an_actionable_error(self):
        for value in [None, "musl 1.2.5", "", OSError("unavailable"), ValueError("unsupported")]:
            with self.subTest(value=value):
                self.system.confstr.side_effect = value if isinstance(value, Exception) else None
                self.system.confstr.return_value = value if not isinstance(value, Exception) else None
                with self.assertRaises(ToolError) as caught:
                    radius.executable()
                self.assertEqual(caught.exception.code, "TIMING_RADIUS_GLIBC_UNAVAILABLE")
                self.assertEqual(caught.exception.extra, {"requiredGlibc": "2.43"})
                self.assertIn("PYMSS_RADIUS", str(caught.exception))
        self.which.assert_not_called()

    def test_platform_without_confstr_reports_unavailable(self):
        del self.system.confstr
        with self.assertRaises(ToolError) as caught:
            radius.executable()
        self.assertEqual(caught.exception.code, "TIMING_RADIUS_GLIBC_UNAVAILABLE")

    def test_explicit_executable_is_not_checked_against_bundled_requirements(self):
        program = self.package / "custom-radius"
        program.write_bytes(b"compatible custom build")
        self.system.environ["PYMSS_RADIUS"] = str(program)
        self.manifest.write_text("invalid metadata", encoding="utf-8")
        self.assertEqual(radius.executable(), program)
        self.system.confstr.assert_not_called()
        self.which.assert_not_called()

    def test_path_and_legacy_flat_programs_keep_their_existing_behavior(self):
        self.program.unlink()
        self.assertEqual(radius.executable(), Path(self.which.return_value).resolve())
        self.system.confstr.assert_not_called()
        flat = self.program.parent.parent / "radius"
        # The existing nested directory must be absent to create the legacy file.
        self.manifest.unlink()
        self.program.parent.rmdir()
        flat.write_bytes(b"legacy layout")
        self.assertEqual(radius.executable(), flat)
        self.system.confstr.assert_not_called()

    def test_other_platforms_do_not_check_linux_requirements(self):
        for target, name in [("win32-x86_64", "radius.exe"), ("darwin-arm64", "radius")]:
            with self.subTest(target=target):
                self.system.name = "nt" if target.startswith("win32-") else "posix"
                radius.current_target.return_value = target
                program = self.package / "bin" / target / "radius" / name
                program.parent.mkdir(parents=True)
                program.write_bytes(b"other platform")
                self.assertEqual(radius.executable(), program)
        self.system.confstr.assert_not_called()

    def test_incomplete_runtime_metadata_requires_reinstallation(self):
        for content in ["invalid JSON", "[]", '{}', '{"requirements":{"glibc":"^2.43"}}']:
            with self.subTest(content=content):
                self.manifest.write_text(content, encoding="utf-8")
                with self.assertRaises(ToolError) as caught:
                    radius.executable()
                self.assertEqual(caught.exception.code, "TIMING_RADIUS_RUNTIME_INVALID")
        self.manifest.unlink()
        with self.assertRaises(ToolError) as caught:
            radius.executable()
        self.assertEqual(caught.exception.code, "TIMING_RADIUS_RUNTIME_INVALID")
        self.which.assert_not_called()


if __name__ == "__main__":
    unittest.main()
