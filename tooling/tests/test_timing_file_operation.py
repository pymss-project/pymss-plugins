from __future__ import annotations

from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from pymss.operations import OperationContext, OperationError, create_runtime
from pymss.operations.files import FileArtifact


ROOT = Path(__file__).resolve().parents[2]


class TimingFileOperationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = create_runtime()
        cls.runtime.load_plugins([ROOT / "plugins"])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "录音.demo.wav"
        tone = (0.1 * np.sin(2 * np.pi * 440 * np.arange(4800) / 48000)).astype(np.float32)
        self.samples = np.stack([tone, tone * 0.5], axis=1)
        sf.write(self.source, self.samples, 48000, subtype="FLOAT")

    def run_file(self, algorithm="rubberband", output_dir=None, n_steps=0, duration_percent=100):
        return self.runtime.run("pymss.timing.process_file",
            inputs={"audio": {"kind": "file", "path": str(self.source)}},
            params={"algorithm": algorithm, "n_steps": n_steps, "duration_percent": duration_percent},
            context=OperationContext(workdir=str(output_dir) if output_dir else None))["audio"]

    def test_plugin_publishes_named_audio_in_the_selected_directory(self):
        output_dir = self.root / "输出目录"
        original = self.source.read_bytes()
        for algorithm in ["rubberband", "radius", "radius_rustfft"]:
            with self.subTest(algorithm=algorithm):
                result = self.run_file(algorithm, output_dir)
                self.assertIsInstance(result, FileArtifact)
                self.assertEqual(result.media_type, "audio/wav")
                path = Path(result.path)
                self.assertEqual(path.parent, output_dir)
                self.assertTrue(path.stem.startswith("录音.demo_processed"))
                saved, rate = sf.read(path, dtype="float32")
                self.assertEqual(rate, 48000)
                np.testing.assert_array_equal(saved, self.samples)
        self.assertEqual(self.source.read_bytes(), original)

    def test_default_directory_and_repeated_exports_preserve_previous_outputs(self):
        first = self.run_file()
        path = Path(first.path)
        original = path.read_bytes()
        second = self.run_file()
        self.assertEqual(path.parent, self.source.parent)
        self.assertEqual(path.name, "录音.demo_processed.wav")
        self.assertNotEqual(first.path, second.path)
        self.assertEqual(path.read_bytes(), original)

    def test_long_source_names_keep_a_readable_suffix(self):
        renamed = self.source.with_name("录音" * 40 + ".wav")
        self.source.rename(renamed)
        self.source = renamed
        result = self.run_file()
        self.assertTrue(Path(result.path).name.endswith("_processed.wav"))
        self.assertLess(len(Path(result.path).name.encode("utf-8")), 255)

    def test_file_operation_rejects_missing_input_without_creating_output(self):
        self.source.unlink()
        output_dir = self.root / "outputs"
        with self.assertRaisesRegex(OperationError, "unavailable"):
            self.run_file(output_dir=output_dir)
        self.assertFalse(output_dir.exists())

    def test_write_failure_does_not_publish_a_partial_or_replace_an_existing_file(self):
        output_dir = self.root / "outputs"
        first = Path(self.run_file(output_dir=output_dir).path)
        original = first.read_bytes()
        with patch("shutil.copyfile", side_effect=OSError("disk failure")):
            with self.assertRaisesRegex(OSError, "disk failure"):
                self.run_file(output_dir=output_dir)
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(list(output_dir.iterdir()), [first])

    def test_cancellation_after_processing_does_not_publish_a_file(self):
        cancelled = False

        def process(waveform, sample_rate, **params):
            nonlocal cancelled
            cancelled = True
            return waveform

        output_dir = self.root / "outputs"
        handler = self.runtime._operations["pymss.timing.process_file"].run
        with patch.dict(handler.__globals__, {"process": process}):
            with self.assertRaisesRegex(OperationError, "cancel"):
                self.runtime.run("pymss.timing.process_file",
                    inputs={"audio": {"kind": "file", "path": str(self.source)}},
                    params={"algorithm": "radius", "n_steps": 3, "duration_percent": 100},
                    context=OperationContext(workdir=str(output_dir), cancelled=lambda: cancelled))
        self.assertFalse(output_dir.exists())

    def test_cli_runs_the_installed_plugin_and_returns_its_saved_file(self):
        from pymss.plugins.install import install

        plugins = self.root / "plugins"
        install(str(ROOT / "plugins/timing"), plugins_dir=plugins, no_deps=True)
        output_dir = self.root / "CLI output"
        scratch = self.root / "scratch"
        scratch.mkdir()
        environment = os.environ.copy()
        environment.pop("PYMSS_PLUGIN_BINDING", None)
        environment["PYMSS_PLUGINS_DIR"] = str(plugins)
        environment["PYMSS_SCRATCH_DIR"] = str(scratch)
        environment["PYMSS_USER_MODELS"] = str(self.root / "user-models.json")
        environment["PYMSS_MODEL_DIR"] = str(self.root / "models")
        result = subprocess.run([sys.executable, "-X", "utf8", "-m", "pymss", "ops", "run", "pymss.timing.process_file",
            "--input", f"audio={self.source}", "--param", "algorithm=radius", "--output-dir", str(output_dir)],
            env=environment, cwd=self.root, capture_output=True, text=True, encoding="utf-8", timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        audio = json.loads(result.stdout)["audio"]
        self.assertEqual(audio["kind"], "file")
        self.assertEqual(audio["mediaType"], "audio/wav")
        self.assertEqual(Path(audio["path"]), output_dir / "录音.demo_processed.wav")
        saved, rate = sf.read(audio["path"], dtype="float32")
        self.assertEqual(rate, 48000)
        np.testing.assert_array_equal(saved, self.samples)
        self.assertEqual(list(scratch.iterdir()), [])

    @unittest.skipUnless(sys.platform in {"win32", "darwin"}, "Packaged native engines require Windows or macOS")
    def test_file_exports_use_both_native_engines_with_monotonic_progress(self):
        from plugins.timing.backend import radius, rubberband

        try:
            radius.executable()
            rubberband.executable()
        except RuntimeError as error:
            self.skipTest(str(error))
        if not shutil.which("ffmpeg") and not Path(os.environ.get("RADIUS_FFMPEG", "")).is_file():
            self.skipTest("FFmpeg is required for Radius file I/O")
        tone = (0.1 * np.sin(2 * np.pi * 440 * np.arange(48000) / 48000)).astype(np.float32)
        sf.write(self.source, np.stack([tone, tone * 0.5], axis=1), 48000, subtype="FLOAT")
        for algorithm in ["radius", "radius_rustfft", "rubberband"]:
            with self.subTest(algorithm=algorithm):
                updates = []
                context = OperationContext(workdir=str(self.root / "native outputs"),
                    progress=lambda fraction, message, event: updates.append(fraction))
                result = self.runtime.run("pymss.timing.process_file",
                    inputs={"audio": {"kind": "file", "path": str(self.source)}},
                    params={"algorithm": algorithm, "n_steps": 3, "duration_percent": 50}, context=context)["audio"]
                saved, rate = sf.read(result.path)
                self.assertEqual(saved.shape, (24000, 2))
                self.assertEqual(rate, 48000)
                self.assertTrue(np.isfinite(saved).all())
                self.assertGreater(float(np.abs(saved).max()), 0.001)
                self.assertEqual(updates, sorted(updates))
                self.assertEqual(updates[-1], 1.0)


if __name__ == "__main__":
    unittest.main()
