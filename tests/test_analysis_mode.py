"""Check publication timing with deterministic decoder/manifest transitions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plotting import run_plotting as analyze


class EndLoop(Exception):
    pass


class AnalysisModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.d = Path(self.temp.name)
        self.events = []
        self.write("config", {"live": False})
        self.write("analysis", {"revision": 1})
        self.write("decode_status", {"status": "running"})
        self.write("manifest", {"chunks": [{"name": "one.root"}, {"name": "two.root"}]})
        events = self.events
        status = self.status

        class Plots:
            def __init__(self, config, analysis):
                self.revision = analysis["revision"]
                self.seen = self.evaluated = self.passed = self.plotted = 0
                events.append(("init", self.revision))

            def add(self, path):
                assert status()["phase"] == "reading_root"
                assert status()["total_chunks"] == 2
                self.seen += 1000
                self.evaluated += 1000
                self.passed += 1000
                self.plotted += 1000
                events.append(("add", self.revision, path.name))

            def save(self):
                assert status()["phase"] == "saving_plots"
                events.append(("save", self.revision, self.seen))

        self.patch = patch.object(analyze, "Plots", Plots)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def write(self, name, value):
        (self.d / (name + ".json")).write_text(json.dumps(value))

    def status(self):
        return json.loads((self.d / "analysis_status.json").read_text())

    def run_loop(self, sleep):
        with patch.object(analyze.time, "sleep", side_effect=sleep), self.assertRaises(EndLoop):
            analyze.run(self.d)

    def test_batch_waits_for_all_decode_then_saves_once_and_exits(self):
        def sleep(_):
            self.assertEqual(self.events, [])
            self.assertEqual(self.status()["status"], "waiting_for_decode")
            self.write("decode_status", {"status": "complete"})

        with patch.object(analyze.time, "sleep", side_effect=sleep) as wait:
            analyze.run(self.d)
        self.assertEqual(wait.call_count, 1)
        self.assertEqual(
            self.events,
            [("init", 1), ("add", 1, "one.root"), ("add", 1, "two.root"), ("save", 1, 2000)],
        )
        self.assertEqual(self.status()["status"], "complete")

    def test_stopped_live_finishes_committed_chunks_and_exits(self):
        self.write("config", {"live": True})
        self.write("decode_status", {"status": "paused"})
        with patch.object(
            analyze.time, "sleep", side_effect=AssertionError("Finished plotter must exit")
        ):
            analyze.run(self.d)
        self.assertEqual(self.status()["status"], "caught_up")
        self.assertEqual(self.events[-1], ("save", 1, 2000))

    def test_live_still_publishes_each_chunk(self):
        self.write("config", {"live": True})

        def sleep(_):
            self.assertEqual(
                self.events,
                [
                    ("init", 1),
                    ("add", 1, "one.root"),
                    ("save", 1, 1000),
                    ("add", 1, "two.root"),
                    ("save", 1, 2000),
                ],
            )
            raise EndLoop

        self.run_loop(sleep)

    def test_batch_never_publishes_partial_result_after_error_or_stop(self):
        for decode, status in [("error", "error"), ("paused", "stopped")]:
            with self.subTest(decode=decode):
                self.write("decode_status", {"status": decode, "error": "bad input"})
                with patch.object(
                    analyze.time, "sleep", side_effect=AssertionError("Stopped plotter must exit")
                ):
                    analyze.run(self.d)
                self.assertEqual(self.events, [])
                self.assertEqual(self.status()["status"], status)
