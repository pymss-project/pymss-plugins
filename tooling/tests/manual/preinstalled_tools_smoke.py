"""Exercise every bundled tool's admission and local file workflows in isolation."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import importlib
import importlib.util
import inspect
import json
import math
import os
import struct
import sys
import tempfile
import types
import wave
from pathlib import Path
from unittest.mock import patch

from studio_plugin_smoke import ROOT, capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--studio-root", required=True, type=Path)
    parser.add_argument(
        "--artifacts", type=Path, default=ROOT / "tooling/.tmp/preinstalled-tools"
    )
    args = parser.parse_args()
    worker = args.studio_root.resolve() / "python"
    sys.path.insert(0, str(worker))
    import pymss.operations
    import pymss.plugins
    import worker_operations
    import worker_plugins
    from pymss_plugin_manager.leases import release_runtime

    def reset():
        # Each synchronous invocation represents a separate Studio worker.
        release_runtime()
        pymss.operations._DEFAULT_RUNTIME = None
        pymss.plugins.reset()

    passed = []
    with tempfile.TemporaryDirectory(prefix="preinstalled-tools-") as temporary, ExitStack() as lifetime:
        lifetime.callback(reset)
        work = Path(temporary)
        root = work / "plugins"
        spec = importlib.util.spec_from_file_location("prepare_plugins", args.studio_root / "scripts/prepare-preinstalled-plugins.py")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        config = {"schemaVersion": 1, "repository": {"url": "https://github.com/pymss-project/pymss-plugins", "ref": "main"},
                  "preinstalled": ["pymss." + name for name in ["convert", "inspect", "sdr", "slicer", "merge", "loudnorm", "asr", "game", "tempo_key"]]}
        files, packages = builder.collect_packages(ROOT, config)
        files[Path("manifest.json")] = json.dumps({"schemaVersion": 1, "plugins": packages}).encode("utf-8")
        bundles = work / "bundles"
        builder.publish(bundles, files)
        env = {
            "PYMSS_PLUGINS_DIR": str(work / "manual"),
            "PYMSS_STUDIO_RUNTIME_ENVS_DIR": str(work / "runtimes"),
            "PYMSS_STUDIO_ACTIVE_RUNTIME_FILE": str(work / "active.json"),
            "PYMSS_STUDIO_LOG_TRANSPORT": "protocol",
            "PYTHONPATH": os.pathsep.join(
                [str(worker), os.environ.get("PYTHONPATH", "")]
            ),
        }
        (work / "active.json").write_text('{"backend":"cpu"}', encoding="utf-8")
        input_dir = work / "input"
        input_dir.mkdir()
        source = input_dir / "source.wav"
        with wave.open(str(source), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(44100)
            stream.writeframes(
                b"".join(
                    struct.pack(
                        "<h", round(4000 * math.sin(2 * math.pi * 440 * i / 44100))
                    )
                    for i in range(44100)
                )
            )
        with (
            patch.dict(os.environ, env),
            patch.object(worker_plugins, "_root", return_value=root),
            patch.object(worker_plugins, "_BUNDLED_ROOT", bundles),
        ):

            def manage(action, name=None):
                reset()
                return capture(
                    worker_plugins.cmd_manage_plugin,
                    {"action": action, "name": "pymss." + name if name else None, "taskId": "tool_lifecycle"},
                )[-1]["payload"]

            def row(snapshot, name):
                return next(
                    item for item in snapshot["installed"] if item["pluginId"] == "pymss." + name
                )

            inventory = capture(
                worker_plugins.cmd_plugin_marketplace, {"includeCatalog": False}
            )[-1]["payload"]
            assert len(inventory["preinstalledPending"]) == 9, inventory
            snapshot = manage("prepare_preinstalled")
            names = {item["name"] for item in snapshot["installed"]}
            assert len(names) == 9, snapshot
            assert all(
                item["preinstalled"]
                and item["enabled"]
                and item["loaded"]
                and item["pluginId"]
                for item in snapshot["installed"]
            ), snapshot
            passed.append("nine-bundled-plugins-discovered-offline")

            def run(name, payload):
                reset()
                operation = row(snapshot, name)["contributions"]["views"][0][
                    "operation"
                ]
                output = work / ("output-" + name)
                payload = {**payload, "outputDir": str(output)}
                inputs = {"request": payload}
                params = {}
                if name == "convert":
                    inputs = {"files": {"paths": payload["inputs"]}}
                    params = {
                        "output_dir": str(output), "sample_rate": payload["sampleRate"],
                        "channels": payload["channels"], "wav_bit_depth": payload["wavBitDepth"],
                    }
                events = capture(
                    worker_operations.cmd_run_operation,
                    {
                        "operation": operation,
                        "inputs": inputs,
                        "params": params,
                        "outputDir": str(output),
                        "requestId": name + "-run",
                    },
                )
                result = next(
                    event["payload"]
                    for event in events
                    if event["type"] == "operation_result"
                )["outputs"]["report"]["value"]
                assert any(event["type"] == "operation_progress" for event in events), (
                    events
                )
                assert all(event["requestId"] == name + "-run" for event in events), (
                    events
                )
                return result

            report = run(
                "convert",
                {
                    "operation": "convert",
                    "inputs": [str(source)],
                    "sampleRate": 48000,
                    "channels": 2,
                    "wavBitDepth": "PCM-16",
                },
            )
            converted = report["outputPaths"][0]
            with wave.open(converted, "rb") as stream:
                assert stream.getframerate() == 48000 and stream.getnchannels() == 2
            passed.append("operation-routes-to-real-converter-plugin")
            report = run("inspect", {"operation": "inspect", "inputPath": str(source)})
            assert report["audioStreams"][0]["sampleRate"] == 44100 and report["raw"]
            passed.append("real-inspect-retains-full-ffprobe-metadata")
            report = run(
                "sdr",
                {
                    "operation": "sdr",
                    "referencePath": str(source),
                    "estimatedPath": str(source),
                },
            )
            assert report["averageSdr"] > 50
            passed.append("real-sdr-file-analysis")
            report = run(
                "slicer",
                {
                    "operation": "slicer",
                    "inputs": [str(source)],
                    "minLength": 100,
                    "minInterval": 100,
                    "hopSize": 10,
                    "maxSilKept": 50,
                },
            )
            assert report["segments"] and all(
                Path(path).is_file() for path in report["outputPaths"]
            )
            passed.append("real-slicer-exports-segments")
            report = run(
                "merge",
                {
                    "operation": "merge",
                    "inputDir": str(input_dir),
                    "sortBy": "name",
                    "sortDirection": "asc",
                },
            )
            assert report["merged"] == 1 and Path(report["outputPath"]).is_file()
            passed.append("real-merge-preserves-ordered-output")
            report = run(
                "loudnorm",
                {
                    "operation": "loudness",
                    "inputs": [str(source)],
                    "measurement": "peak",
                    "target": -12,
                    "useLimiter": False,
                },
            )
            assert report["succeeded"] == 1 and report["measurements"]
            passed.append("real-loudness-measurement-and-output")

            class AutoModel:
                def __init__(self, **kwargs):
                    pass

                def generate(self, **kwargs):
                    return [
                        {
                            "text": "Transcribed text",
                            "sentence_info": [
                                {"start": 0, "end": 500, "text": "Transcribed text"}
                            ],
                        }
                    ]

            previous_funasr = sys.modules.get("funasr")
            sys.modules["funasr"] = types.SimpleNamespace(AutoModel=AutoModel)
            try:
                report = run(
                    "asr",
                    {
                        "operation": "asr",
                        "inputPath": str(source),
                        "outputFormats": ["txt", "json", "srt"],
                    },
                )
            finally:
                # Preserve native modules imported during inference; unloading
                # and importing PyTorch again in one process is unsupported.
                if previous_funasr is None:
                    sys.modules.pop("funasr", None)
                else:
                    sys.modules["funasr"] = previous_funasr
            assert (
                report["text"] == "Transcribed text" and len(report["outputPaths"]) == 3
            )
            passed.append("packaged-asr-fake-backend-produces-all-transcripts")
            reset()
            snapshot_run = worker_plugins.operation_runtime()
            handler = inspect.getclosurevars(snapshot_run._operations["pymss.game.tool"].run).nonlocals["handler"]
            package = handler.__module__.split(".backend.")[0]
            assert Path(sys.modules[package].__file__).resolve() == (Path(row(snapshot, "game")["path"]) / "__init__.py").resolve()
            inference = importlib.import_module(package + ".backend.engine.infer")
            model = work / "game.pt"
            model.touch()
            output = work / "output-game"
            output.mkdir()
            midi = output / "source.mid"
            midi.write_bytes(b"MThd")
            result = inference.MidiInferenceResult(midi, 3, 1.0, 0.0, 0.5, ())
            # Keep this worker's runtime so the fake belongs to its actual installed module.
            with (
                patch.object(inference, "infer", return_value=result),
                patch.object(worker_operations, "_runtime", return_value=snapshot_run),
            ):
                events = capture(
                    worker_operations.cmd_run_operation,
                    {
                        "operation": "pymss.game.tool",
                        "inputs": {
                            "request": {
                                "operation": "midi",
                                "inputPath": str(source),
                                "modelPath": str(model),
                                "outputDir": str(output),
                                "bpm": 120,
                            }
                        },
                        "params": {},
                        "outputDir": str(output),
                        "requestId": "midi-run",
                    },
                )
            assert events[-1]["payload"]["outputs"]["report"]["value"]["noteCount"] == 3
            passed.append("packaged-game-resolves-its-own-inference-modules")
            # BPM analysis is supplied by the installed plugin, including its native runtime.
            tempo = row(snapshot, "tempo_key")
            assert (
                "operations" in tempo["contributions"]["views"][0]["permissions"]
                and set(tempo["operations"])
                == {"pymss.tempo_key.tool", "pymss.tempo_key.analyze", "pymss.tempo_key.detect_bpm"}
            )
            passed.append("binary-analysis-plugin-admission")
            beat_source = input_dir / "beats.wav"
            with wave.open(str(source), "rb") as stream:
                pulse = stream.readframes(1024)
            half_beat = pulse + bytes((22050 - 1024) * 2)
            with wave.open(str(beat_source), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(44100)
                stream.writeframes(half_beat * 72)
            reset()
            events = capture(
                worker_operations.cmd_run_operation,
                {
                    "operation": "pymss.tempo_key.detect_bpm",
                    "inputs": {"audio": str(beat_source)},
                    "params": {},
                    "outputDir": str(work / "output-bpm"),
                    "requestId": "bpm-run",
                },
            )
            assert events[-1]["type"] == "operation_result", events
            report = events[-1]["payload"]["outputs"]["report"]["value"]
            assert report["duration"] == 36 and report["roundedBpm"] > 0, report
            passed.append("bundled-native-bpm-operation-runs-through-worker")
            snapshot = manage("disable", "convert")
            assert (
                not row(snapshot, "convert")["enabled"]
                and not row(snapshot, "convert")["loaded"]
            )
            reset()
            events = capture(
                worker_operations.cmd_run_operation,
                {
                    "operation": "pymss.convert.batch",
                    "inputs": {"request": {"inputs": [str(source)]}},
                    "params": {},
                    "outputDir": str(work / "disabled-convert"),
                    "requestId": "disabled-convert-run",
                },
                expected_code=1,
            )
            assert events[-1]["type"] == "error", events
            assert events[-1]["payload"]["code"] == "OPERATION_UNAVAILABLE", events
            assert not (work / "disabled-convert").exists()
            snapshot = manage("enable", "convert")
            assert row(snapshot, "convert")["loaded"]
            snapshot = manage("uninstall", "convert")
            assert "pymss.convert" not in {item["name"] for item in snapshot["installed"]}
            snapshot = manage("prepare_preinstalled")
            assert "pymss.convert" not in {item["name"] for item in snapshot["installed"]}
            snapshot = manage("install_preinstalled", "convert")
            assert row(snapshot, "convert")["loaded"]
            passed.append("disable-remove-and-explicit-reinstall-honor-user-choice")
    args.artifacts.mkdir(parents=True, exist_ok=True)
    (args.artifacts / "results.json").write_text(
        json.dumps({"passed": passed}, indent=2), encoding="utf-8"
    )
    print(f"Preinstalled tools smoke passed: {len(passed)} checks")


if __name__ == "__main__":
    main()
