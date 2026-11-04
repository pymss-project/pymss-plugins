import os
import platform
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugins.game.backend.mlx_backend import is_apple_silicon
from plugins.timing.backend import radius, rubberband


class WindowsPlatformQueryTests(unittest.TestCase):
    def test_packaged_timing_engines_are_found_without_wmi(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for module, variable, name in [(radius, "PYMSS_RADIUS", "radius"), (rubberband, "PYMSS_RUBBERBAND", "rubberband")]:
                filename = name + (".exe" if os.name == "nt" else "")
                executable = root / "bin/win32-x86_64" / name / filename
                executable.parent.mkdir(parents=True)
                executable.write_bytes(b"native engine fixture")
                executable.chmod(0o755)
                with self.subTest(engine=name), \
                        patch.object(sys, "platform", "win32"), \
                        patch.dict(os.environ, {variable: "", "PROCESSOR_ARCHITECTURE": "AMD64", "PROCESSOR_ARCHITEW6432": ""}), \
                        patch.object(platform, "machine", side_effect=AssertionError("WMI queried")), \
                        patch.object(module, "__file__", str(root / "backend" / f"{name}.py")):
                    self.assertEqual(module.executable(), executable)

    def test_mlx_backend_check_does_not_query_windows_system_information(self):
        with patch.object(sys, "platform", "win32"), \
                patch.object(platform, "system", side_effect=AssertionError("WMI queried")), \
                patch.object(platform, "machine", side_effect=AssertionError("WMI queried")):
            self.assertFalse(is_apple_silicon())
