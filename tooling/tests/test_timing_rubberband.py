from __future__ import annotations

import os
import platform
from pathlib import Path
import shutil
import tempfile
import sys
import unittest
from unittest.mock import patch

import numpy as np

from pymss.graph.core import AudioArtifact
from pymss.operations import OperationContext, OperationError, create_runtime
from plugins.timing.backend import rubberband

ROOT = Path(__file__).resolve().parents[2]


class TimingValidationTests(unittest.TestCase):
    def setUp(self):
        rubberband._versions.clear()

    def test_invalid_inputs_fail_before_native_process_or_scratch_files(self):
        calls = [
            lambda: rubberband.time_stretch([], 16000, 1),
            lambda: rubberband.time_stretch([np.nan], 16000, 1),
            lambda: rubberband.time_stretch(np.zeros((1, 2, 3)), 16000, 1),
            lambda: rubberband.time_stretch([0], 16000, 0),
            lambda: rubberband.time_stretch([0], 0, 1),
            lambda: rubberband.time_stretch([0], 16000.5, 1),
            lambda: rubberband.time_stretch([0], 16000, True),
            lambda: rubberband.pitch_shift([0], 16000, np.inf),
            lambda: rubberband.pitch_shift([0], 16000, 2, 12.5),
            lambda: rubberband.pitch_shift([0], 16000, 24, 1),
        ]
        with patch.object(rubberband, "executable") as native:
            for call in calls:
                with self.subTest(call=call), self.assertRaises(ValueError):
                    call()
            native.assert_not_called()

    def test_explicit_invalid_runtime_never_falls_back_to_path(self):
        with patch.dict(os.environ, {"PYMSS_RUBBERBAND": "/does-not-exist/rubberband"}), patch.object(shutil, "which") as which:
            with self.assertRaisesRegex(RuntimeError, "PYMSS_RUBBERBAND"):
                rubberband.executable()
            which.assert_not_called()

    def test_packaged_runtime_supports_both_current_and_legacy_layouts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            machine = platform.machine().lower()
            target = f"{sys.platform}-" + {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
            name = "rubberband.exe" if os.name == "nt" else "rubberband"
            legacy = root / "bin" / target / name
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(b"legacy executable")
            legacy.chmod(0o755)
            with patch.dict(os.environ, {"PYMSS_RUBBERBAND": ""}), \
                 patch.object(rubberband, "__file__", str(root / "backend/rubberband.py")), \
                 patch.object(shutil, "which", side_effect=AssertionError("packaged runtime should win")):
                self.assertEqual(rubberband.executable(), legacy)
                nested = legacy.parent / "rubberband" / name
                if legacy == nested.parent:
                    legacy.unlink()
                nested.parent.mkdir()
                nested.write_bytes(b"current executable")
                nested.chmod(0o755)
                self.assertEqual(rubberband.executable(), nested)

    def test_neutral_transform_is_an_exact_copy_without_a_native_runtime(self):
        source = np.array([[0, 1.5, -2]], dtype=np.float32)
        with patch.object(rubberband, "executable", side_effect=AssertionError("not needed")):
            result = rubberband.pitch_shift(source, 16000, 0)
        np.testing.assert_array_equal(result, source)
        self.assertIsNot(result, source)

    def test_capability_uses_calling_operations_cancellation(self):
        from pymss.plugins.kit import operation_context

        with operation_context(OperationContext(cancelled=lambda: True)), \
             patch.object(rubberband, "executable") as native, \
             self.assertRaisesRegex(OperationError, "cancel"):
            rubberband.time_stretch([0.1], 16000, 2)
        native.assert_not_called()

    def test_clipped_native_output_is_retried_and_gain_is_restored(self):
        import soundfile as sf
        import subprocess
        import sys

        audio = np.ones((2, 2048), dtype=np.float32)
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {"PYMSS_SCRATCH_DIR": directory}), \
             patch.object(rubberband, "executable", return_value=Path(sys.executable)), \
             patch("pymss.plugins.kit.run_native_process", return_value=subprocess.CompletedProcess([], 0, "", "4.0.0")), \
             patch.object(sf, "read", side_effect=[(np.ones((2048, 2), dtype=np.float32), 16000),
                                                  (np.full((2048, 2), 0.05, dtype=np.float32), 16000)]), \
             patch.object(sf, "write") as write:
            output = rubberband.pitch_shift(audio, 16000, 12)
            self.assertEqual(write.call_count, 2)
            np.testing.assert_allclose(write.call_args_list[1].args[1], audio.T / 32)
            np.testing.assert_allclose(output, audio * 1.6)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_old_native_version_is_rejected_before_writing_audio(self):
        import soundfile as sf
        import subprocess
        import sys
        from pymss.plugins.kit import ToolError

        with patch.object(rubberband, "executable", return_value=Path(sys.executable)), \
             patch("pymss.plugins.kit.run_native_process", return_value=subprocess.CompletedProcess([], 0, "", "2.0.2")), \
             patch.object(sf, "write") as write:
            with self.assertRaises(ToolError) as raised:
                rubberband.pitch_shift([0.1], 16000, 1)
            self.assertEqual(raised.exception.code, "TIMING_RUNTIME_UNSUPPORTED")
            write.assert_not_called()

    def test_missing_runtime_is_actionable_and_registration_stays_lazy(self):
        with patch.dict(os.environ, {"PYMSS_RUBBERBAND": ""}), patch.object(Path, "is_file", return_value=False), patch.object(shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "PYMSS_RUBBERBAND"):
                rubberband.executable()
        with patch.object(rubberband, "executable", side_effect=AssertionError("must stay lazy")):
            runtime = create_runtime()
            reports = runtime.load_plugins([ROOT / "plugins"], validate_plugin=lambda p: None if p.name == "timing" else (_ for _ in ()).throw(ValueError("unselected")))
            timing = next(row for row in reports if row.get("plugin_id") == "pymss.timing")
            self.assertTrue(timing["loaded"], timing)
            self.assertEqual(len([spec for spec in runtime.list_operations() if spec["id"].startswith("pymss.timing.")]), 3)


class TimingNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            rubberband.executable()
        except RuntimeError as error:
            raise unittest.SkipTest(str(error))
        cls.runtime = create_runtime()
        reports = cls.runtime.load_plugins([ROOT / "plugins"])
        if not all(row["loaded"] for row in reports):
            raise AssertionError(reports)

    def setUp(self):
        rubberband._versions.clear()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.scratch = Path(temporary.name)
        setting = patch.dict(os.environ, {"PYMSS_SCRATCH_DIR": str(self.scratch)})
        setting.start()
        self.addCleanup(setting.stop)
        self.rate = 16000
        self.tone = (0.1 * np.sin(2 * np.pi * 440 * np.arange(32000) / self.rate)).astype(np.float32)

    def frequency(self, audio):
        stable = audio[4000:-4000]
        spectrum = np.abs(np.fft.rfft(stable * np.hanning(len(stable))))
        return np.argmax(spectrum) * self.rate / len(stable)

    def test_pitch_shift_preserves_duration_and_uses_steps_per_octave(self):
        for steps, bins, expected in [(12, 12, 880), (-12, 12, 220), (12, 24, 440 * 2 ** 0.5)]:
            with self.subTest(steps=steps, bins=bins):
                output = rubberband.pitch_shift(self.tone, self.rate, steps, bins)
                self.assertEqual(output.shape, self.tone.shape)
                self.assertEqual(output.dtype, np.float32)
                self.assertAlmostEqual(self.frequency(output), expected, delta=3)
                self.assertEqual(list(self.scratch.iterdir()), [])

    def test_short_audio_preserves_layout_and_requested_duration(self):
        for frames, rate in [(1, 4), (16, 0.5), (64, 1.5), (128, 1.5)]:
            for stereo in (False, True):
                with self.subTest(frames=frames, rate=rate, stereo=stereo):
                    source = np.linspace(0.1, 0.2, frames, dtype=np.float32)
                    if stereo:
                        source = np.stack([source, -source * 0.5])
                    result = rubberband.time_stretch(source, self.rate, rate)
                    expected_frames = max(1, round(frames / rate))
                    self.assertEqual(result.shape, (2, expected_frames) if stereo else (expected_frames,))
                    self.assertTrue(np.isfinite(result).all())
                    self.assertGreater(float(np.abs(result).max()), 0)
                    self.assertEqual(list(self.scratch.iterdir()), [])
        pitched = rubberband.pitch_shift(np.full(16, 0.1, dtype=np.float32), self.rate, 12)
        self.assertEqual(pitched.shape, (16,))
        self.assertTrue(np.isfinite(pitched).all())

    def test_stretch_preserves_pitch_channels_and_float_headroom(self):
        other = 0.75 * np.sin(2 * np.pi * 660 * np.arange(len(self.tone)) / self.rate)
        stereo = np.stack([self.tone * 15, other]).astype(np.float32)
        for rate in (0.5, 2):
            with self.subTest(rate=rate):
                output = rubberband.time_stretch(stereo, self.rate, rate)
                self.assertEqual(output.shape, (2, round(stereo.shape[1] / rate)))
                self.assertAlmostEqual(self.frequency(output[0]), 440, delta=3)
                self.assertAlmostEqual(self.frequency(output[1]), 660, delta=3)
                self.assertGreater(np.abs(output).max(), 1.2)
                self.assertEqual(list(self.scratch.iterdir()), [])

    def test_operation_uses_current_samples_and_preserves_audio_metadata(self):
        artifact = AudioArtifact(np.stack([self.tone, -self.tone]), self.rate,
                                 source_path="/missing/original.wav", stem_name="vocals", channel_layout="stereo")
        output = self.runtime.run("pymss.timing.time_stretch", inputs={"audio": artifact}, params={"rate": 2})["audio"]
        self.assertEqual(output.audio.shape, (2, 16000))
        self.assertEqual((output.source_path, output.stem_name, output.channel_layout),
                         (artifact.source_path, artifact.stem_name, artifact.channel_layout))
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_unified_operation_changes_pitch_and_duration_with_real_progress(self):
        updates = []
        context = OperationContext(progress=lambda fraction, message, event: updates.append(fraction))
        artifact = AudioArtifact(self.tone.reshape(1, -1), self.rate)
        result = self.runtime.run("pymss.timing.process", inputs={"audio": artifact},
                                  params={"n_steps": 12, "duration_percent": 200, "algorithm": "rubberband"}, context=context)["audio"]
        self.assertEqual(result.audio.shape, (1, len(self.tone) * 2))
        self.assertAlmostEqual(self.frequency(result.audio[0]), 880, delta=3)
        self.assertTrue(any(0.05 < fraction < 1 for fraction in updates), updates)
        self.assertEqual(updates, sorted(updates))
        self.assertEqual(updates[-1], 1)

    def test_non_ascii_scratch_path_and_multichannel_audio(self):
        scratch = self.scratch / "音频 空间"
        scratch.mkdir()
        source = np.stack([self.tone * (index + 1) / 6 for index in range(6)])
        with patch.dict(os.environ, {"PYMSS_SCRATCH_DIR": str(scratch)}):
            result = rubberband.time_stretch(source, self.rate, 1.3)
        self.assertEqual(result.shape, (6, round(source.shape[1] / 1.3)))
        self.assertTrue(np.isfinite(result).all())
        self.assertEqual(list(scratch.iterdir()), [])

    def test_cancellation_reaps_native_process_and_allows_retry(self):
        started = []

        def cancelled():
            files = list(self.scratch.glob("*/output.wav"))
            started.extend(files)
            return bool(files)

        context = OperationContext(cancelled=cancelled)
        # A long R3 job ensures cancellation occurs before normal completion.
        audio = AudioArtifact(np.tile(self.tone, 120).reshape(1, -1), self.rate)
        with self.assertRaisesRegex(OperationError, "cancel"):
            self.runtime.run("pymss.timing.time_stretch", inputs={"audio": audio}, params={"rate": 0.25}, context=context)
        self.assertTrue(started, "native output must be opened before cancelling")
        self.assertEqual(list(self.scratch.iterdir()), [])
        result = rubberband.time_stretch(self.tone, self.rate, 2)
        self.assertEqual(result.shape, (16000,))

    def test_missing_native_dependency_failure_cleans_scratch_and_keeps_error_code(self):
        from pymss.plugins.kit import ToolError

        with patch("pymss.plugins.kit.run_native_process", side_effect=ToolError("COMMAND_EXIT_FAILED", "native failed", extra={"stderr": "missing sndfile"})):
            with self.assertRaisesRegex(ToolError, "missing sndfile") as raised:
                rubberband.pitch_shift(self.tone, self.rate, 1)
        self.assertEqual(raised.exception.code, "COMMAND_EXIT_FAILED")
        self.assertEqual(list(self.scratch.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
