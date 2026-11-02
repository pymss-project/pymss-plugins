from __future__ import annotations

import unittest

from plugins.timing.backend.progress import NativeProgress
from pymss.operations import OperationContext


class NativeProgressTests(unittest.TestCase):
    def tracker(self, engine):
        values = []
        return NativeProgress(OperationContext(progress=lambda fraction, message, event: values.append(fraction)), engine), values

    def test_radius_counter_is_streamed_across_chunk_boundaries_and_never_regresses(self):
        progress, values = self.tracker("radius")
        progress("stderr", "vc  [======      ]  25.")
        progress("stderr", "0% 0.5s elapsed\nvc [===] 50.0%\n")
        progress("stderr", "vc [===] 10.0%\n")
        progress("stdout", "vc [===] 100.0%\n")
        self.assertEqual(values, [0.275, 0.5])

    def test_rubberband_analysis_and_processing_are_two_native_stages(self):
        progress, values = self.tracker("rubberband")
        progress("stderr", "Pass 1: Studying...\r10% \r100% \rCalculating profile...\n")
        progress("stderr", "Pass 2: Processing...\r10% \r100% \n")
        for actual, expected in zip(values, [0.075, 0.3, 0.365, 0.95], strict=True):
            self.assertAlmostEqual(actual, expected)
        progress("stderr", "Pass 1: Studying...\r10%\n")
        self.assertEqual(values[-1], 0.95)

    def test_malformed_percentages_do_not_abort_processing(self):
        progress, values = self.tracker("radius")
        progress("stderr", "vc [===] .%\nvc [===] 1.2.3%\nvc [===] 20.0%\n")
        self.assertEqual(len(values), 1)
        self.assertAlmostEqual(values[0], 0.23)
