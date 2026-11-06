from __future__ import annotations

import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

from plugins.tempo_key.backend import operations, rba
from pymss.operations import OperationContext, OperationError, create_runtime
from pymss.plugins.kit import ToolError, operation_context

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "plugins/tempo_key"
DIAGNOSTICS = "  samples         : 176400 (4.00 s @ 44100 Hz)\n  onsets (slope)  : 4\n"
duration_reader = rba._duration_seconds


def native_result(bpm="119.95", key="A major", *, bpm_only=False, onsets=4, duration=None):
    output = "input.wav\tBPM: " + bpm + ("" if bpm_only else "\tKEY: " + key) + "\n"
    detail = DIAGNOSTICS.replace(": 4\n", f": {onsets}\n")
    if duration is None:
        duration = 60 if bpm_only else 4
    detail = detail.replace("176400", str(round(duration * 44100))).replace("4.00 s", f"{duration:.2f} s")
    return subprocess.CompletedProcess([], 0, output, detail)


class TempoKeyProtocolTests(unittest.TestCase):
    def test_file_names_with_tabs_and_newlines_cannot_change_result_fields(self):
        output = "name\tBPM: 999.00\nKEY: forged.wav\tBPM: 119.95\tKEY: Bb minor\n"
        self.assertEqual(rba.parse_report(output, DIAGNOSTICS, bpm_only=False),
                         {"bpm": 119.95, "key": "Bb minor", "duration": 4.0})

    def test_duration_comes_from_exact_decoded_sample_count(self):
        result = native_result()
        detail = result.stderr.replace("176400 (4.00 s", "176401 (4.00 s")
        self.assertEqual(rba.parse_report(result.stdout, detail, bpm_only=False)["duration"], 176401 / 44100)

    def test_invalid_or_non_finite_native_reports_are_rejected(self):
        good = native_result()
        for output, detail in [
            ("", DIAGNOSTICS), ("BPM: NaN\n", DIAGNOSTICS),
            (good.stdout.replace("119.95", "-1.00"), DIAGNOSTICS),
            (good.stdout.replace("A major", "not a key"), DIAGNOSTICS),
            (good.stdout, ""), (good.stdout, DIAGNOSTICS * 2),
            (good.stdout, DIAGNOSTICS.replace("44100 Hz", "0 Hz")),
            (good.stdout, DIAGNOSTICS.replace("176400", "0")),
        ]:
            with self.subTest(output=output, detail=detail):
                with self.assertRaises(ToolError) as caught:
                    rba.parse_report(output, detail, bpm_only=False)
                self.assertEqual(caught.exception.code, "TEMPO_KEY_INVALID_OUTPUT")

    def test_native_duration_limit_is_also_checked_after_analysis(self):
        result = native_result()
        with self.assertRaises(ToolError) as caught:
            rba.parse_report(result.stdout, DIAGNOSTICS.replace("176400", str(44100 * 1801)), bpm_only=False)
        self.assertEqual(caught.exception.code, "TEMPO_KEY_DURATION_LIMIT")


class TempoKeyAdapterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "音频 source.wav"
        self.source.write_bytes(b"metadata mocked")
        for active in [patch.object(rba, "executable", return_value=self.root / "rba.exe"),
                       patch.object(rba, "_duration_seconds", return_value=60.0)]:
            active.start()
            self.addCleanup(active.stop)

    def test_native_io_is_default_and_explicit_decoder_settings_are_passed_unchanged(self):
        for environment in [{}, {"RBA_USE_FFMPEG": "1", "RBA_FFMPEG": "/configured/ffmpeg"},
                            {"rba_use_ffmpeg": "1", "rba_ffmpeg": "/lower/ffmpeg"},
                            {"RBA_FFMPEG": "/path/alone-does-not-enable"}]:
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True), \
                    patch.object(rba, "run_native_process", return_value=native_result()) as launch:
                expected = dict(os.environ)
                result = rba.analyze_file(self.source)
                self.assertEqual(result["bpm"], 119.95)
                args, options = launch.call_args
                self.assertEqual(args[0][-2:], ["--", str(self.source)])
                self.assertEqual(options["environment"], expected)
                self.assertEqual(dict(os.environ), expected)
                self.assertEqual(options["cwd"], self.source.parent)

    def test_bpm_only_uses_upstream_flag_and_rounds_halves_up(self):
        with patch.object(rba, "run_native_process", return_value=native_result("120.50", bpm_only=True)) as launch:
            result = rba.analyze_file(self.source, bpm_only=True)
        self.assertIn("--bpmonly", launch.call_args.args[0])
        self.assertEqual(result, {"bpm": 120.5, "roundedBpm": 121, "duration": 60.0})

    def test_short_clip_prior_cannot_replace_a_manual_midi_bpm(self):
        for duration in [0.01, 4, 12, 24, 29.99]:
            with self.subTest(duration=duration), patch.object(rba, "_duration_seconds", return_value=duration), \
                    patch.object(rba, "run_native_process", return_value=native_result(bpm_only=True, duration=duration)), \
                    self.assertRaises(ToolError) as caught:
                rba.analyze_file(self.source, bpm_only=True)
            self.assertEqual(caught.exception.code, "TEMPO_KEY_TOO_SHORT")
        with patch.object(rba, "run_native_process", return_value=native_result(bpm_only=True, duration=29.99)), \
                self.assertRaises(ToolError) as caught:
            rba.analyze_file(self.source, bpm_only=True)
        self.assertEqual(caught.exception.code, "TEMPO_KEY_TOO_SHORT")

    def test_estimated_metadata_duration_does_not_reject_a_complete_long_clip(self):
        with patch.object(rba, "_duration_seconds", return_value=29.24), \
                patch.object(rba, "run_native_process", return_value=native_result(bpm_only=True, duration=31.03)):
            report = rba.analyze_file(self.source, bpm_only=True)
        self.assertEqual(report["roundedBpm"], 120)

    def test_unsupported_source_rates_never_reach_the_native_resampler(self):
        for rate in [1, 999, 768001, 1000000]:
            with wave.open(str(self.source), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(rate)
                stream.writeframes(bytes(64))
            with self.subTest(rate=rate):
                with patch.object(rba, "_duration_seconds", duration_reader), \
                        patch.object(rba, "run_native_process", return_value=native_result()) as launch, \
                        self.assertRaises(ToolError) as caught:
                    rba.analyze_file(self.source)
                self.assertEqual(caught.exception.code, "TEMPO_KEY_UNSUPPORTED_SAMPLE_RATE")
                launch.assert_not_called()

    def test_extreme_or_invalid_analysis_rates_are_rejected_before_allocating_native_memory(self):
        for key in ["RBA_SAMPLE_RATE", "rba_sample_rate"]:
            for rate in ["1", "7999", "192001", "1000000000", "4294967295", "-1", "NaN", "", "9" * 5000]:
                with self.subTest(key=key, rate=rate[:20]), patch.dict(os.environ, {key: rate}, clear=True), \
                        patch.object(rba, "run_native_process") as launch, self.assertRaises(ToolError) as caught:
                    rba.analyze_file(self.source)
                self.assertEqual(caught.exception.code, "TEMPO_KEY_INVALID_SAMPLE_RATE")
                launch.assert_not_called()
        for rate in ["0", "8000", "44100", "192000"]:
            with self.subTest(rate=rate), patch.dict(os.environ, {"RBA_SAMPLE_RATE": rate}, clear=True), \
                    patch.object(rba, "run_native_process", return_value=native_result()) as launch:
                rba.analyze_file(self.source)
            self.assertEqual(launch.call_args.kwargs["environment"]["RBA_SAMPLE_RATE"], rate)

    def test_silence_prior_or_insufficient_onsets_never_replace_manual_bpm(self):
        for bpm, onsets in [("0.00", 4), ("120.00", 0), ("120.00", 1)]:
            with self.subTest(bpm=bpm, onsets=onsets):
                with patch.object(rba, "run_native_process", return_value=native_result(bpm, bpm_only=True, onsets=onsets)), \
                        self.assertRaises(ToolError) as caught:
                    rba.analyze_file(self.source, bpm_only=True)
                self.assertEqual(caught.exception.code, "TEMPO_KEY_NO_BPM")

    def test_long_files_and_cancellation_are_rejected_before_starting_native_code(self):
        with patch.object(rba, "run_native_process") as launch:
            with patch.object(rba, "_duration_seconds", return_value=1801), self.assertRaises(ToolError) as caught:
                rba.analyze_file(self.source)
            self.assertEqual(caught.exception.code, "TEMPO_KEY_DURATION_LIMIT")
            with self.assertRaisesRegex(OperationError, "cancel"):
                rba.analyze_file(self.source, context=OperationContext(cancelled=lambda: True))
            launch.assert_not_called()

    def test_missing_duration_is_reported_without_running_a_decoder(self):
        container = Mock()
        container.streams.audio = [Mock(duration=None, time_base=None)]
        container.duration = None
        with patch("av.open") as open_audio:
            open_audio.return_value.__enter__.return_value = container
            with self.assertRaises(ToolError) as caught:
                duration_reader(self.source)
            self.assertEqual(caught.exception.code, "TEMPO_KEY_DURATION_UNKNOWN")
            open_audio.return_value.__exit__.assert_called_once()

    def test_timeout_and_cancellation_propagate_from_the_managed_process(self):
        script = self.root / "slow.py"
        script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        for cancel in [False, True]:
            started = time.monotonic()
            context = OperationContext(cancelled=lambda: cancel and time.monotonic() - started > 0.15)
            with self.subTest(cancel=cancel):
                with patch.object(rba, "executable", return_value=Path(sys.executable)), \
                        patch.object(rba, "TIMEOUT_SECONDS", 0.3), self.assertRaises(OperationError if cancel else ToolError) as caught:
                    rba.analyze_file(script, context=context)
                if not cancel:
                    self.assertEqual(caught.exception.code, "COMMAND_TIMEOUT")
                self.assertLess(time.monotonic() - started, 5)


class TempoKeyOperationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = create_runtime()
        cls.runtime.load_plugins([ROOT / "plugins"])

    def test_single_file_operations_have_cli_usable_file_inputs(self):
        for name in ["analyze", "detect_bpm"]:
            spec = self.runtime.describe_operation("pymss.tempo_key." + name)
            self.assertEqual(spec["inputs"], {"audio": {"type": "file"}})
            self.assertEqual(spec["outputs"], {"report": {"type": "object"}})

    def test_batch_retains_partial_failures_and_deduplicates_inputs(self):
        updates = []
        context = OperationContext(progress=lambda fraction, message, event: updates.append((fraction, event)))
        def analyze(path, **options):
            if path == "bad.wav":
                raise ToolError("TEMPO_KEY_DURATION_UNKNOWN", "Duration unavailable")
            return {"bpm": 120.0, "key": "C major", "duration": 4.0}
        with patch.object(operations, "executable"), patch.object(operations, "analyze_file", side_effect=analyze) as native, operation_context(context):
            result = operations._batch({"inputs": ["good.wav", "bad.wav", "good.wav"]})
        self.assertEqual(native.call_count, 2)
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failed"][0]["code"], "TEMPO_KEY_DURATION_UNKNOWN")
        self.assertEqual([value for value, _ in updates], [0, 0.5, 0.5, 1])
        self.assertTrue(all(event["type"] == "audio_tool_progress" for _, event in updates))

    def test_all_failures_keep_the_first_error_code(self):
        with patch.object(operations, "executable"), patch.object(operations, "analyze_file", side_effect=ToolError("TEMPO_KEY_NO_BPM", "No onsets")), \
                operation_context(OperationContext()), self.assertRaises(ToolError) as caught:
            operations._batch({"inputs": ["a.wav", "b.wav"]})
        self.assertEqual(caught.exception.code, "TEMPO_KEY_NO_BPM")
        self.assertEqual(len(caught.exception.extra["failed"]), 2)

    def test_cancellation_during_a_batch_stops_before_the_next_file(self):
        cancelled = False
        def analyze(*args, **kwargs):
            nonlocal cancelled
            cancelled = True
            return {"bpm": 120.0, "key": "C major", "duration": 4.0}
        with patch.object(operations, "executable"), patch.object(operations, "analyze_file", side_effect=analyze) as native, \
                operation_context(OperationContext(cancelled=lambda: cancelled)), self.assertRaisesRegex(OperationError, "cancel"):
            operations._batch({"inputs": ["a.wav", "b.wav"]})
        self.assertEqual(native.call_count, 1)


class TempoKeyRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("prepare_tempo_key", PACKAGE / "scripts/prepare_runtime.py")
        cls.prepare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.prepare)

    def test_all_packaged_binaries_match_the_pinned_provenance(self):
        import hashlib
        for target, (asset, checksum) in self.prepare.RELEASES.items():
            directory = PACKAGE / "bin" / target / "rba"
            program = directory / ("rba.exe" if target.startswith("win32-") else "rba")
            manifest = json.loads((directory / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual(hashlib.sha256(program.read_bytes()).hexdigest(), checksum)
            self.assertEqual((manifest["asset"], manifest["sourceCommit"], manifest["version"]),
                             (asset, self.prepare.COMMIT, self.prepare.VERSION))
            self.assertIn("GNU GENERAL PUBLIC LICENSE", (directory / "LICENSE.rba").read_text(encoding="utf-8"))
            if target.startswith("linux-"):
                self.assertEqual(manifest["requirements"]["glibc"], ">=2.35")

    def test_preparation_rejects_wrong_hash_and_preserves_an_existing_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "invalid.exe"
            invalid.write_bytes(b"wrong binary")
            with self.assertRaisesRegex(ValueError, "SHA256"):
                self.prepare.prepare("win32-x86_64", root / "bin", binary=invalid)
            self.assertFalse((root / "bin/win32-x86_64/rba").exists())
            source = PACKAGE / "bin/win32-x86_64/rba/rba.exe"
            result = self.prepare.prepare("win32-x86_64", root / "bin", binary=source)
            original = (result / "rba.exe").read_bytes()
            with self.assertRaisesRegex(ValueError, "already exists"):
                self.prepare.prepare("win32-x86_64", root / "bin", binary=source)
            self.assertEqual((result / "rba.exe").read_bytes(), original)


class TempoKeyGlibcTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.package = Path(temporary.name) / "tempo_key"
        self.program = self.package / "bin/linux-x86_64/rba/rba"
        self.program.parent.mkdir(parents=True)
        self.program.write_bytes(b"never executed")
        self.manifest = self.program.with_name("runtime.json")
        self.manifest.write_text(json.dumps({"requirements": {"glibc": ">=2.35"}}), encoding="utf-8")
        self.system = SimpleNamespace(name="posix", environ={}, X_OK=os.X_OK,
                                      access=Mock(return_value=True), confstr=Mock(return_value="glibc 2.34"))
        for active in [patch.object(rba, "os", self.system),
                       patch.object(rba, "__file__", str(self.package / "backend/rba.py")),
                       patch.object(rba, "current_target", return_value="linux-x86_64")]:
            active.start()
            self.addCleanup(active.stop)
        active = patch.object(rba.shutil, "which", return_value="/system/rba")
        self.which = active.start()
        self.addCleanup(active.stop)

    def test_incompatible_bundled_runtime_fails_without_switching_to_path(self):
        with self.assertRaises(ToolError) as caught:
            rba.executable()
        self.assertEqual(caught.exception.code, "TEMPO_KEY_RBA_GLIBC_UNSUPPORTED")
        self.assertEqual(caught.exception.extra, {"requiredGlibc": "2.35", "currentGlibc": "2.34"})
        self.which.assert_not_called()

    def test_equal_and_newer_glibc_versions_are_compared_numerically(self):
        for version in ["2.35", "2.35.1", "2.100", "3.0"]:
            with self.subTest(version=version):
                self.system.confstr.return_value = "glibc " + version
                self.assertEqual(rba.executable(), self.program)
        self.system.confstr.return_value = "glibc 2.9"
        with self.assertRaises(ToolError):
            rba.executable()

    def test_unknown_libc_is_distinct_from_broken_runtime_metadata(self):
        self.system.confstr.return_value = "musl 1.2.5"
        with self.assertRaises(ToolError) as caught:
            rba.executable()
        self.assertEqual(caught.exception.code, "TEMPO_KEY_RBA_GLIBC_UNAVAILABLE")
        self.manifest.write_text("[]", encoding="utf-8")
        with self.assertRaises(ToolError) as caught:
            rba.executable()
        self.assertEqual(caught.exception.code, "TEMPO_KEY_RBA_RUNTIME_INVALID")

    def test_explicit_runtime_override_bypasses_packaged_requirements(self):
        custom = self.package / "custom-rba"
        custom.write_bytes(b"custom program")
        self.system.environ["PYMSS_RBA"] = str(custom)
        self.assertEqual(rba.executable(), custom)
        self.system.confstr.assert_not_called()
        self.system.environ["PYMSS_RBA"] = str(self.package / "missing")
        with self.assertRaises(ToolError) as caught:
            rba.executable()
        self.assertEqual(caught.exception.code, "TEMPO_KEY_RBA_MISSING")
        self.which.assert_not_called()


class TempoKeyNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.program = rba.executable()
        except ToolError as error:
            raise unittest.SkipTest(str(error)) from error

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "节拍 input.wav"
        rate = 44100
        import array
        samples = array.array("h", (int(12000 * math.sin(2 * math.pi * 440 * i / rate)
                                        * math.exp(-((i % (rate // 2)) / rate) * 30)) for i in range(rate * 36)))
        with wave.open(str(self.source), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(rate)
            stream.writeframes(samples.tobytes())
        settings = patch.dict(os.environ)
        settings.start()
        self.addCleanup(settings.stop)
        for name in ["PYMSS_RBA", "RBA_USE_FFMPEG", "rba_use_ffmpeg", "RBA_SAMPLE_RATE", "rba_sample_rate"]:
            os.environ.pop(name, None)

    def test_native_decoder_runs_without_ffmpeg_on_path(self):
        with patch.dict(os.environ, {"PATH": "", "RBA_FFMPEG": "/missing/ffmpeg"}):
            result = rba.analyze_file(self.source)
        self.assertGreater(result["bpm"], 0)
        self.assertEqual(result["duration"], 36)
        self.assertIn(result["key"].split()[-1], ["major", "minor"])

    def test_opt_in_ffmpeg_backend_and_bpm_only_operation_work(self):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("No external FFmpeg available for opt-in verification")
        with patch.dict(os.environ, {"RBA_USE_FFMPEG": "1", "RBA_FFMPEG": ffmpeg}):
            result = rba.analyze_file(self.source, bpm_only=True)
        self.assertAlmostEqual(result["bpm"], 120, delta=3)
        self.assertEqual(result["roundedBpm"], 120)
        self.assertNotIn("key", result)

    def test_silence_does_not_produce_a_measured_midi_bpm(self):
        with wave.open(str(self.source), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(44100)
            stream.writeframes(bytes(44100 * 2 * 36))
        with self.assertRaises(ToolError) as caught:
            rba.analyze_file(self.source, bpm_only=True)
        self.assertEqual(caught.exception.code, "TEMPO_KEY_NO_BPM")

    def test_installed_plugin_owns_its_runtime_and_needs_no_studio_service(self):
        from pymss.plugins.install import install

        with tempfile.TemporaryDirectory() as directory:
            installed = install(str(PACKAGE), plugins_dir=Path(directory), no_deps=True)
            runtime = create_runtime()
            reports = runtime.load_plugins([installed.path.parent])
            self.assertTrue(all(row["loaded"] for row in reports), reports)
            function = runtime._operations["pymss.tempo_key.analyze"].run
            backend = importlib.import_module(function.__globals__["__package__"] + ".rba")
            self.assertTrue(backend.executable().is_relative_to(installed.path))
            result = runtime.run("pymss.tempo_key.detect_bpm", inputs={"audio": str(self.source)}, params={})
            self.assertEqual(result["report"]["roundedBpm"], 120)
