from __future__ import annotations

import os
import importlib
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from plugins.timing.backend import operations, radius
from pymss.graph.core import AudioArtifact
from pymss.operations import OperationContext, OperationError, create_runtime
from pymss.plugins.kit import ToolError

ROOT = Path(__file__).resolve().parents[2]


class TimingAlgorithmTests(unittest.TestCase):
    def test_unsupported_radius_sample_rate_fails_before_starting_native_code(self):
        with patch.object(radius, "executable") as native:
            with self.assertRaises(ToolError) as raised:
                radius.pitch_shift([0.1], 16000, 3)
            self.assertEqual(raised.exception.code, "TIMING_RADIUS_SAMPLE_RATE_UNSUPPORTED")
            native.assert_not_called()

    def test_radius_rejects_non_identity_speed_before_running_native_code(self):
        with patch.object(radius, "pitch_shift") as native:
            with self.assertRaisesRegex(ValueError, "speed_percent must be 100"):
                operations.process([0.1], 48000, n_steps=3, speed_percent=140, algorithm="radius")
            native.assert_not_called()

    def test_pitch_routes_only_to_selected_engine_and_preserves_legacy_default(self):
        audio = [0.1]
        with patch.object(operations, "_rubberband_pitch_shift") as rubber, patch.object(radius, "pitch_shift") as rad:
            operations.pitch_shift(audio, 48000, 3)
            rubber.assert_called_once_with(audio, 48000, 3, 12)
            rad.assert_not_called()
            rubber.reset_mock()
            operations.pitch_shift(audio, 48000, 3, 24, "radius")
            rad.assert_called_once_with(audio, 48000, 3, 24)
            rubber.assert_not_called()
            with self.assertRaisesRegex(ValueError, "algorithm"):
                operations.pitch_shift(audio, 48000, 3, algorithm="unknown")

    def test_missing_radius_preserves_selection_and_does_not_fall_back(self):
        with patch.dict(os.environ, {"PYMSS_RADIUS": "/no-such-radius"}), patch.object(operations, "_rubberband_pitch_shift") as rubber:
            with self.assertRaises(ToolError) as raised:
                operations.pitch_shift([0.1], 48000, 3, algorithm="radius")
            self.assertEqual(raised.exception.code, "TIMING_RADIUS_MISSING")
            rubber.assert_not_called()

    def test_stretch_schema_offers_no_radius_selector(self):
        runtime = create_runtime()
        runtime.load_plugins([ROOT / "plugins"])
        spec = runtime.describe_operation("pymss.timing.time_stretch")
        self.assertNotIn("algorithm", spec["params"]["properties"])
        pitch = runtime.describe_operation("pymss.timing.pitch_shift")
        self.assertEqual(pitch["params"]["properties"]["algorithm"]["default"], "rubberband")
        with self.assertRaises(OperationError):
            runtime.run("pymss.timing.time_stretch", inputs={"audio": AudioArtifact(np.ones((1, 8), dtype=np.float32), 48000)},
                        params={"rate": 2, "algorithm": "radius"})


class RadiusNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            radius.executable()
        except RuntimeError as error:
            raise unittest.SkipTest(str(error))
        cls.runtime = create_runtime()
        cls.runtime.load_plugins([ROOT / "plugins"])
        package = cls.runtime._operations["pymss.timing.pitch_shift"].run.__globals__["__package__"]
        cls.operation_backend = importlib.import_module(package + ".radius")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.scratch = Path(temporary.name) / "Radius 音频"
        self.scratch.mkdir()
        setting = patch.dict(os.environ, {"PYMSS_SCRATCH_DIR": str(self.scratch), "PYMSS_RUBBERBAND": "/not-required"})
        setting.start()
        self.addCleanup(setting.stop)
        self.rate = 48000
        self.tone = (0.1 * np.sin(2 * np.pi * 440 * np.arange(self.rate * 2) / self.rate)).astype(np.float32)

    def frequency(self, wave):
        stable = wave[16000:-16000]
        return np.argmax(np.abs(np.fft.rfft(stable * np.hanning(len(stable))))) * self.rate / len(stable)

    def test_pitch_operation_preserves_layout_duration_and_uses_current_samples(self):
        source = AudioArtifact(np.stack([self.tone, self.tone * 0.5]), self.rate,
                               source_path="/missing/provenance.wav", stem_name="vocals", channel_layout="stereo")
        updates = []
        context = OperationContext(progress=lambda fraction, message, event: updates.append(fraction))
        result = self.runtime.run("pymss.timing.process", inputs={"audio": source},
                                  params={"n_steps": 3, "algorithm": "radius", "speed_percent": 100}, context=context)["audio"]
        self.assertEqual(result.audio.shape, source.audio.shape)
        self.assertAlmostEqual(self.frequency(result.audio[0]), 440 * 2 ** 0.25, delta=3)
        self.assertEqual((result.source_path, result.stem_name, result.channel_layout),
                         (source.source_path, source.stem_name, source.channel_layout))
        self.assertEqual(list(self.scratch.iterdir()), [])
        self.assertTrue(any(0.05 < fraction < 1 for fraction in updates), updates)
        self.assertEqual(updates, sorted(updates))
        self.assertEqual(updates[-1], 1)

    def test_fractional_downshift_matches_upstream_cli_and_preserves_headroom(self):
        import soundfile as sf
        from pymss.plugins.kit import run_native_process

        result = operations.pitch_shift(self.tone * 15, self.rate, -12, 24, "radius")
        self.assertEqual(result.shape, self.tone.shape)
        # The current upstream VC's pure-tone result has a measurable pitch
        # deviation. Test adapter parity rather than hiding or correcting it.
        with tempfile.TemporaryDirectory(dir=self.scratch) as directory:
            work = Path(directory)
            sf.write(work / "input.wav", self.tone * 15, self.rate, subtype="FLOAT")
            run_native_process([str(radius.executable()), "input.wav", "direct.wav", "--mode", "vc", "--semitones", "-6",
                                "--tempo", "100", "--bit-depth", "32f", "--no-progress"], cwd=work, timeout=45)
            expected, _ = sf.read(work / "direct.wav", dtype="float32")
        np.testing.assert_array_equal(result, expected)
        self.assertLess(self.frequency(result), 440)
        self.assertGreater(float(np.abs(result).max()), 1.2)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_cancellation_cleans_scratch_and_allows_retry(self):
        started = []
        original = self.operation_backend._run

        def run(*args, **kwargs):
            started.append(time.monotonic())
            return original(*args, **kwargs)

        context = OperationContext(cancelled=lambda: bool(started) and time.monotonic() - started[0] > 0.8)
        source = AudioArtifact(np.tile(self.tone, 5).reshape(1, -1), self.rate)
        with patch.object(self.operation_backend, "_run", side_effect=run), self.assertRaisesRegex(OperationError, "cancel"):
            self.runtime.run("pymss.timing.pitch_shift", inputs={"audio": source}, params={"n_steps": 3, "algorithm": "radius"}, context=context)
        self.assertTrue(started)
        self.assertEqual(list(self.scratch.iterdir()), [])
        retry = operations.pitch_shift(self.tone, self.rate, 3, algorithm="radius")
        self.assertEqual(retry.shape, self.tone.shape)


if __name__ == "__main__":
    unittest.main()
