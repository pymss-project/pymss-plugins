"""Expose rba analysis through the shared pymss Operation contract."""
from __future__ import annotations

from pathlib import Path

from pymss.plugins.kit import ToolError, current_operation_context, emit, register_tool

from .rba import analyze_file, executable

MAX_INPUT_FILES = 1000


def _batch(request):
    context = current_operation_context()
    values = request.get("inputs")
    if not isinstance(values, list) or not values or len(values) > MAX_INPUT_FILES:
        raise ValueError(f"Provide between 1 and {MAX_INPUT_FILES} input audio files.")
    if any(not isinstance(path, str) or not path.strip() for path in values):
        raise ValueError("Input audio paths must be non-empty strings.")
    paths = list(dict.fromkeys(path.strip() for path in values))
    executable()  # A missing runtime is one actionable failure, not one per file.
    items, failed = [], []
    for index, path in enumerate(paths):
        context.check_cancelled()
        emit("audio_tool_progress", {"operation": "tempo_key", "completed": index, "total": len(paths),
                                     "current": Path(path).name, "phase": "analyzing_tempo_key"})
        try:
            report = analyze_file(path, context=context)
            items.append({"path": path, "fileName": Path(path).name, **report})
        except Exception as error:
            if getattr(error, "code", None) in {"TASK_CANCELLED", "OPERATION_CANCELLED"}:
                raise
            context.check_cancelled()
            failed.append({"path": path, "message": str(error),
                           "code": getattr(error, "code", "TEMPO_KEY_ANALYSIS_FAILED")})
        context.check_cancelled()
        emit("audio_tool_progress", {"operation": "tempo_key", "completed": index + 1, "total": len(paths),
                                     "current": Path(path).name, "phase": "analyzing_tempo_key"})
    if not items:
        raise ToolError(failed[0]["code"], failed[0]["message"], recoverable=True, extra={"failed": failed})
    return {"operation": "tempo_key", "items": items, "succeeded": len(items), "failed": failed}


def setup(plugin):
    from pymss.operations.files import input_file

    for operation, title, bpm_only in [
        ("pymss.tempo_key.analyze", "BPM and Key Analysis", False),
        ("pymss.tempo_key.detect_bpm", "BPM Detection", True),
    ]:
        def run(context, inputs, params, bpm_only=bpm_only):
            context.check_cancelled()
            report = analyze_file(input_file(inputs["audio"]), bpm_only=bpm_only, context=context)
            context.report_progress(1.0, "Analysis completed")
            return {"report": report}

        plugin.register_operation(id=operation, title=title,
                                  description="Analyze an audio file with the packaged rba runtime",
                                  inputs={"audio": {"type": "file"}},
                                  params={"type": "object", "properties": {}, "additionalProperties": False},
                                  outputs={"report": {"type": "object"}}, run=run)
    register_tool(plugin, "pymss.tempo_key.tool", _batch, title="BPM and Key Detection", tool="tempo_key")
