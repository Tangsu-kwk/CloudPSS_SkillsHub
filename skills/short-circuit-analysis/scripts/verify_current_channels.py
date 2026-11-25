"""Offline checks for the current-signal selection used by run and resume."""

import unittest

from short_circuit.runtime import _select_declared_current_traces


class Result:
    def __init__(self, *plots):
        self.plots = plots

    def getPlots(self):
        return [{"title": f"Plot {index}"} for index in range(len(self.plots))]

    def getPlotChannelNames(self, index):
        return self.plots[index]

    def getPlotChannelData(self, index, name):
        return {"x": [0, 1], "y": [0, 2]}


class CurrentChannelTests(unittest.TestCase):
    def channels(self, result, dimension=None, limit=3):
        source = {"channel": "#I", "current_unit": {"signal_dimension": dimension}}
        return [row["channel"] for row in _select_declared_current_traces(result, limit, [source])]

    def test_scalar_formats(self):
        for name in ("#I", "#I:0"):
            with self.subTest(name=name):
                self.assertEqual(self.channels(Result([name]), 1), [name])

    def test_order_and_limit(self):
        result = Result(["#I:2", "#Other:1", "#I:0"], ["#I:1"])
        self.assertEqual(self.channels(result, 3, limit=2), ["#I:0", "#I:1"])

    def test_incomplete_vectors(self):
        for names, dimension in [(["#I:0", "#I:2"], None), (["#I:0", "#I:1"], 3)]:
            with self.subTest(names=names, dimension=dimension):
                with self.assertRaisesRegex(ValueError, "expected.*contiguous"):
                    self.channels(Result(names), dimension, limit=1)

    def test_duplicate_and_mixed_encodings(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.channels(Result(["#I:0"], ["#I:0"]), 1)
        with self.assertRaisesRegex(ValueError, "Inconsistent"):
            self.channels(Result(["#I", "#I:0"]), 1)


if __name__ == "__main__":
    unittest.main()
