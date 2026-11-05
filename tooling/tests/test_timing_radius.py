from __future__ import annotations

import os
import importlib
from pathlib import Path
import platform
import sys
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
    def test_radius_enables_ffmpeg_io_without_changing_the_parent_environment(self):
        import soundfile as sf

        def render(argv, *, cwd, environment, **options):
            self.assertEqual(environment["RADIUS_FFMPEG_IO"], "1")
            self.assertEqual(environment["RADIUS_FFMPEG"], "/configured/ffmpeg")
            self.assertEqual(environment["RADIUS_PROGRESS"], "1")
            sf.write(cwd / "output.wav", np.zeros((4096, 1), dtype=np.float32), 48000, subtype="FLOAT")

        with patch.dict(os.environ, {"RADIUS_FFMPEG_IO": "0", "RADIUS_FFMPEG": "/configured/ffmpeg"}), \
             patch.object(radius, "executable", return_value=Path("radius.exe")), \
             patch.object(radius, "_run", side_effect=render):
            radius.process(np.zeros(4096, dtype=np.float32), 48000, 3)
            self.assertEqual(os.environ["RADIUS_FFMPEG_IO"], "0")

    def test_unsupported_radius_sample_rate_fails_before_starting_native_code(self):
        with patch.object(radius, "executable") as native:
            for sr in [7999, 192001]:
                with self.subTest(sr=sr), self.assertRaises(ToolError) as raised:
                    radius.pitch_shift([0.1], sr, 3)
                self.assertEqual(raised.exception.code, "TIMING_RADIUS_SAMPLE_RATE_UNSUPPORTED")
            native.assert_not_called()

    def test_duration_percent_has_the_same_meaning_for_both_engines(self):
        from plugins.timing.backend import rubberband

        for duration, rate in [(50, 2), (100, 1), (200, 0.5)]:
            with self.subTest(duration=duration), patch.object(radius, "process") as native, patch.object(rubberband, "process") as other:
                operations.process([0.1], 48000, 3, duration, "radius")
                native.assert_called_once_with([0.1], 48000, 3, duration, fft="radix2")
                other.assert_not_called()
                operations.process([0.1], 48000, 3, duration, "rubberband")
                other.assert_called_once_with([0.1], 48000, pitch=2 ** (3 / 12), rate=rate)

    def test_radius_duration_routes_to_the_selected_engine(self):
        with patch.object(radius, "process") as native, patch.object(operations, "_rubberband_pitch_shift") as other:
            operations.process([0.1], 48000, n_steps=3, duration_percent=140, algorithm="radius")
            native.assert_called_once_with([0.1], 48000, 3, 140, fft="radix2")
            other.assert_not_called()

    def test_radius_passes_duration_directly_and_rounds_final_frames(self):
        import soundfile as sf

        audio = np.ones((2, 13), dtype=np.float32) * 0.1
        for duration, tempo, frames in [(50, "50", 7), (100, "100", 13), (200, "200", 26)]:
            with self.subTest(duration=duration):
                def render(argv, *, cwd, **options):
                    self.assertEqual(argv[argv.index("--tempo") + 1], tempo)
                    self.assertEqual(argv[argv.index("--semitones") + 1], "3")
                    sf.write(cwd / "output.wav", np.zeros((frames, 2), dtype=np.float32), 48000, subtype="FLOAT")

                with patch.object(radius, "executable", return_value=Path("radius.exe")), patch.object(radius, "_run", side_effect=render):
                    result = radius.process(audio, 48000, 3, duration)
                self.assertEqual(result.shape, (2, frames))

    def test_neutral_radius_processing_returns_an_exact_independent_copy(self):
        audio = np.array([0.1, -1.5, 2.0], dtype=np.float32)
        with patch.object(radius, "executable") as native:
            result = radius.process(audio, 48000)
        native.assert_not_called()
        np.testing.assert_array_equal(result, audio)
        self.assertFalse(np.shares_memory(result, audio))

    def test_radius_rejects_invalid_duration_and_empty_target_before_native_code(self):
        with patch.object(radius, "executable") as native:
            for duration in [0, 401, float("nan"), True]:
                with self.subTest(duration=duration), self.assertRaises(ValueError):
                    radius.process([0.1], 48000, 3, duration)
            with self.assertRaisesRegex(ValueError, "empty audio output"):
                radius.process([0.1], 48000, 3, 25)
            native.assert_not_called()

    def test_pitch_routes_only_to_selected_engine_and_preserves_legacy_default(self):
        audio = [0.1]
        with patch.object(operations, "_rubberband_pitch_shift") as rubber, patch.object(radius, "pitch_shift") as rad:
            operations.pitch_shift(audio, 48000, 3)
            rubber.assert_called_once_with(audio, 48000, 3, 12)
            rad.assert_not_called()
            rubber.reset_mock()
            operations.pitch_shift(audio, 48000, 3, 24, "radius")
            rad.assert_called_once_with(audio, 48000, 3, 24, fft="radix2")
            rubber.assert_not_called()
            with self.assertRaisesRegex(ValueError, "algorithm"):
                operations.pitch_shift(audio, 48000, 3, algorithm="unknown")

    def test_missing_radius_preserves_selection_and_does_not_fall_back(self):
        with patch.dict(os.environ, {"PYMSS_RADIUS": "/no-such-radius"}), patch.object(operations, "_rubberband_pitch_shift") as rubber:
            with self.assertRaises(ToolError) as raised:
                operations.pitch_shift([0.1], 48000, 3, algorithm="radius")
            self.assertEqual(raised.exception.code, "TIMING_RADIUS_MISSING")
            rubber.assert_not_called()

    def test_rustfft_selection_routes_both_operations_to_the_requested_backend(self):
        with patch.object(radius, "process") as native, patch.object(radius, "pitch_shift") as pitch:
            operations.process([0.1], 48000, 3, 140, "radius_rustfft")
            native.assert_called_once_with([0.1], 48000, 3, 140, fft="rustfft")
            operations.pitch_shift([0.1], 48000, 3, 24, "radius_rustfft")
            pitch.assert_called_once_with([0.1], 48000, 3, 24, fft="rustfft")

    def test_fft_backend_is_passed_to_cli_and_invalid_values_never_start_it(self):
        import soundfile as sf

        for fft in ["radix2", "rustfft"]:
            def render(argv, *, cwd, **options):
                self.assertEqual(argv[argv.index("--fft") + 1], fft)
                sf.write(cwd / "output.wav", np.zeros((4096, 1), dtype=np.float32), 48000, subtype="FLOAT")

            with self.subTest(fft=fft), patch.object(radius, "executable", return_value=Path("radius.exe")), \
                    patch.object(radius, "_run", side_effect=render):
                radius.process(np.zeros(4096, dtype=np.float32), 48000, 3, fft=fft)
        with patch.object(radius, "executable") as native:
            with self.assertRaisesRegex(ValueError, "fft"):
                radius.process([0.1], 48000, fft="unknown")
            native.assert_not_called()

    def test_stretch_schema_offers_no_radius_selector(self):
        runtime = create_runtime()
        runtime.load_plugins([ROOT / "plugins"])
        spec = runtime.describe_operation("pymss.timing.time_stretch")
        self.assertNotIn("algorithm", spec["params"]["properties"])
        pitch = runtime.describe_operation("pymss.timing.pitch_shift")
        self.assertEqual(pitch["params"]["properties"]["algorithm"]["default"], "rubberband")
        for operation in ["pymss.timing.pitch_shift", "pymss.timing.process", "pymss.timing.process_file"]:
            self.assertEqual(runtime.describe_operation(operation)["params"]["properties"]["algorithm"]["enum"],
                             ["rubberband", "radius", "radius_rustfft"])
        with self.assertRaises(OperationError):
            runtime.run("pymss.timing.time_stretch", inputs={"audio": AudioArtifact(np.ones((1, 8), dtype=np.float32), 48000)},
                        params={"rate": 2, "algorithm": "radius"})


class TimingInstalledRuntimeTests(unittest.TestCase):
    def test_installed_plugin_uses_its_own_binaries_and_reports_progress(self):
        from pymss.plugins.install import install

        machine = platform.machine().lower()
        target = f"{sys.platform}-" + {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
        if not (ROOT / "plugins/timing/bin" / target / "radius").is_dir():
            self.skipTest("No bundled Radius for this platform")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ):
            os.environ.pop("PYMSS_RADIUS", None)
            os.environ.pop("PYMSS_RUBBERBAND", None)
            installed = install(str(ROOT / "plugins/timing"), plugins_dir=Path(directory) / "plugins", no_deps=True)
            runtime = create_runtime()
            runtime.load_plugins([installed.path.parent])
            package = runtime._operations["pymss.timing.process"].run.__globals__["__package__"]
            bundled = [engine for engine in ["radius", "rubberband"]
                       if (ROOT / "plugins/timing/bin" / target / engine).is_dir()]
            for engine in bundled:
                backend = importlib.import_module(package + "." + engine)
                self.assertTrue(backend.executable().is_relative_to(installed.path))
            for sr in [16000, 44100, 48000, 96000]:
                frames = sr // 4
                wave = (0.1 * np.sin(2 * np.pi * 440 * np.arange(frames) / sr)).astype(np.float32)
                source = AudioArtifact(np.stack([wave, wave * 0.5]), sr)
                for engine in ["radius", "radius_rustfft"] + (["rubberband"] if "rubberband" in bundled else []):
                    for duration in [50, 200]:
                        with self.subTest(engine=engine, sr=sr, duration=duration):
                            updates = []
                            context = OperationContext(progress=lambda fraction, message, event: updates.append(fraction))
                            result = runtime.run("pymss.timing.process", inputs={"audio": source},
                                params={"algorithm": engine, "n_steps": 3, "duration_percent": duration}, context=context)["audio"]
                            self.assertEqual(result.audio.ndim, 2)
                            self.assertEqual(result.audio.shape[0], 2)
                            # At a half-frame boundary either nearest integer preserves the requested duration.
                            self.assertLessEqual(abs(result.audio.shape[1] - frames * duration / 100), 0.5)
                            self.assertEqual(result.sample_rate, sr)
                            self.assertTrue(np.isfinite(result.audio).all())
                            self.assertGreater(float(np.abs(result.audio).max()), 0.001)
                            self.assertTrue(any(0.05 < value < 1 for value in updates), updates)
                            self.assertEqual(updates, sorted(updates))
                            self.assertEqual(updates[-1], 1)


class TimingDurationNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from plugins.timing.backend import rubberband

        try:
            radius.executable()
            rubberband.executable()
        except RuntimeError as error:
            raise unittest.SkipTest(str(error))
        cls.runtime = create_runtime()
        cls.runtime.load_plugins([ROOT / "plugins"])

    def test_both_engines_produce_half_original_and_double_duration(self):
        sr = 48000
        frames = sr // 2
        wave = (0.1 * np.sin(2 * np.pi * 440 * np.arange(frames) / sr)).astype(np.float32)
        source = AudioArtifact(np.stack([wave, wave * 0.5]), sr)
        for algorithm in ("radius", "radius_rustfft", "rubberband"):
            for duration in (50, 100, 200):
                with self.subTest(algorithm=algorithm, duration=duration):
                    result = self.runtime.run("pymss.timing.process", inputs={"audio": source},
                                              params={"algorithm": algorithm, "n_steps": 0,
                                                      "duration_percent": duration})["audio"]
                    self.assertEqual(result.audio.shape, (2, frames * duration // 100))
                    self.assertEqual(result.sample_rate, sr)
                    self.assertTrue(np.isfinite(result.audio).all())
                    self.assertGreater(float(np.abs(result.audio).max()), 0.001)


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

    def test_native_radius_preserves_sample_rate_across_the_supported_range(self):
        for sr in [8000, 12345, 16000, 22050, 32000, 88200, 96000, 192000]:
            with self.subTest(sr=sr):
                frames = sr // 2
                wave = (0.1 * np.sin(2 * np.pi * 440 * np.arange(frames) / sr)).astype(np.float32)
                source = AudioArtifact(np.stack([wave, wave * 0.5]), sr)
                result = self.runtime.run("pymss.timing.process", inputs={"audio": source},
                    params={"n_steps": 3, "duration_percent": 100, "algorithm": "radius"})["audio"]
                self.assertEqual(result.sample_rate, sr)
                self.assertEqual(result.audio.shape, source.audio.shape)
                self.assertTrue(np.isfinite(result.audio).all())
                self.assertGreater(float(np.abs(result.audio).max()), 0.001)

    def test_pitch_operation_preserves_layout_duration_and_uses_current_samples(self):
        source = AudioArtifact(np.stack([self.tone, self.tone * 0.5]), self.rate,
                               source_path="/missing/provenance.wav", stem_name="vocals", channel_layout="stereo")
        updates = []
        context = OperationContext(progress=lambda fraction, message, event: updates.append(fraction))
        result = self.runtime.run("pymss.timing.process", inputs={"audio": source},
                                  params={"n_steps": 3, "algorithm": "radius", "duration_percent": 100}, context=context)["audio"]
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
        # Preserve native output without introducing pitch or level correction.
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

    def test_duration_changes_match_current_native_output_at_both_sample_rates(self):
        import soundfile as sf
        from pymss.plugins.kit import run_native_process

        for sr, channels, duration, steps in [(44100, 1, 50, 0), (48000, 2, 200, 3), (48000, 1, 100, 3)]:
            with self.subTest(sample_rate=sr, channels=channels, duration=duration):
                tone = (0.1 * np.sin(2 * np.pi * 440 * np.arange(sr) / sr)).astype(np.float32)
                samples = tone if channels == 1 else np.stack([tone, tone * 0.5])
                source = AudioArtifact(np.atleast_2d(samples), sr, source_path="/missing/source.wav", stem_name="vocals")
                result = self.runtime.run("pymss.timing.process", inputs={"audio": source},
                                          params={"algorithm": "radius", "n_steps": steps, "duration_percent": duration})["audio"]
                self.assertEqual((result.source_path, result.stem_name), (source.source_path, source.stem_name))
                actual = result.audio[0] if channels == 1 else result.audio
                frames = sr * duration // 100
                self.assertEqual(actual.shape, (frames,) if channels == 1 else (channels, frames))
                with tempfile.TemporaryDirectory(dir=self.scratch) as directory:
                    work = Path(directory)
                    sf.write(work / "input.wav", samples.T, sr, subtype="FLOAT")
                    run_native_process([str(radius.executable()), "input.wav", "direct.wav", "--mode", "vc",
                                        "--semitones", str(steps), "--tempo", str(duration),
                                        "--bit-depth", "32f", "--no-progress"], cwd=work, timeout=45)
                    expected, rate = sf.read(work / "direct.wav", dtype="float32", always_2d=True)
                self.assertEqual(rate, sr)
                np.testing.assert_array_equal(actual, expected[:, 0] if channels == 1 else expected.T)
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
