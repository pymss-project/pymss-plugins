"""Translate native processing counters into monotone Operation progress."""
from __future__ import annotations

import re


class NativeProgress:
    def __init__(self, context, engine):
        self.context = context
        self.engine = engine
        self.stage = "study"
        self.partial = ""
        self.last = 0.05

    def __call__(self, channel: str, text: str):
        if channel != "stderr":
            return
        value = self.partial + text
        lines = re.split(r"[\r\n]", value)
        self.partial = lines.pop()[-4096:]
        # A progress repaint can lack a final newline. Parse it now as well;
        # the monotonic filter suppresses re-reading the same fragment.
        for line in [*lines, self.partial]:
            if self.engine == "radius":
                match = re.search(r"^\s*(?:vc|td)\s+\[[^]]*\]\s*(\d+(?:\.\d+)?)%", line)
                if match is None:
                    continue
                fraction = 0.05 + 0.9 * min(100.0, float(match[1])) / 100
                message = "Processing audio (Radius)"
            else:
                if "Pass 1:" in line:
                    self.stage = "study"
                elif "Pass 2:" in line:
                    self.stage = "process"
                match = re.search(r"\b(\d+(?:\.\d+)?)%", line)
                if match is None:
                    continue
                percent = min(100.0, float(match[1])) / 100
                fraction = 0.05 + 0.25 * percent if self.stage == "study" else 0.3 + 0.65 * percent
                message = "Analyzing audio (Rubber Band R3)" if self.stage == "study" else "Processing audio (Rubber Band R3)"
            if fraction >= self.last + 0.005:
                self.context.check_cancelled()
                self.last = fraction
                self.context.report_progress(fraction, message)
