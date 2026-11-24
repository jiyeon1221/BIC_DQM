"""Verify worker startup, decoder integration, and legacy checkpoint recovery."""
import os
import json
from pathlib import Path
import pickle
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from decoding.nkdaq_reader import NKTail
from decoding.rcdaq_decoder import rc_decoder
from matching.timestamp_matcher import TimeMatcher
from matching.trigger_matcher import NKJoin
from processing.session_manager import Controller
from processing.event_pipeline import Pipeline
from storage.event_data import Event, Wave
from storage.root_writer import root
from storage.session_state import load_checkpoint
from test_live import packet
import test_streaming


class PackageLayoutTests(unittest.TestCase):
    def test_previous_module_paths_in_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            config = test_streaming.StreamingTest.two_inputs(directory)
            pipeline = Pipeline(config)
            pipeline.sources[0].pending[7] = Event(7, 8.0, {"A": Wave(7, 8.0, [1, 2, 3])})
            core = types.ModuleType("core")
            worker = types.ModuleType("worker")
            classes = (Wave, Event, NKTail, NKJoin, TimeMatcher, Pipeline)
            originals = {cls: cls.__module__ for cls in classes}
            try:
                for cls in classes:
                    module = worker if cls is Pipeline else core
                    setattr(module, cls.__name__, cls)
                    cls.__module__ = module.__name__
                with patch.dict(sys.modules, core=core, worker=worker):
                    (directory / "checkpoint.pkl").write_bytes(pickle.dumps(pipeline, protocol=5))
            finally:
                for cls, name in originals.items():
                    cls.__module__ = name
            restored = load_checkpoint(directory / "checkpoint.pkl")
            self.assertIsInstance(restored, Pipeline)
            self.assertIsInstance(restored.sources[0], NKTail)
            self.assertIsInstance(restored.join, NKJoin)
            self.assertIsInstance(restored.matcher, TimeMatcher)
            self.assertEqual(restored.sources[0].pending[7].waves["A"].adc, [1, 2, 3])

    def test_rc_adapter_loads_from_new_location(self):
        decode = rc_decoder()
        with tempfile.TemporaryDirectory() as temp:
            result = decode(
                str(Path(temp) / "missing.evt"), 0, 1088, root().std.vector("int")([139]), True
            )
            self.assertEqual(result.next, 0)
            self.assertEqual(len(result.waves), 0)

    def test_controller_runs_real_processing_and_plotting_workers(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            config = test_streaming.StreamingTest.two_inputs(directory)
            config.update(matching=False, live=False, plot_name="decoded_1.root")
            config["mapping"][1]["z"] = 1
            for mid in (41, 42):
                (directory / f"Run_00001_BIC_{mid}.dat").write_bytes(
                    b"".join(packet(i, mid=mid) for i in range(12))
                )
            analysis = dict(
                method="PeakADC",
                type="single",
                count=10,
                first=0,
                cuts=[],
                revision=1,
                jobs=[
                    dict(channels=["A", "B"], executable="draw_peakADC", requires_matching=False)
                ],
            )
            controller = Controller(dict(os.environ), directory / "plots")
            controller.base = directory / "sessions"
            controller.plan = lambda request: dict(config=dict(config), analysis=analysis)
            try:
                status = controller.start(dict(run=1, live=False))
                session = status["session"]
                deadline = time.monotonic() + 60
                while status["processing"] and time.monotonic() < deadline:
                    time.sleep(0.1)
                    status = controller.status(session)
                self.assertEqual(status["decode"]["status"], "complete", status)
                self.assertEqual(status["analysis"]["status"], "complete", status)
                self.assertEqual(status["analysis"]["plotted"], 20)
                self.assertEqual(len(status["files"]), 1)
                self.assertTrue(
                    (directory / "plots/NKDAQ/run_00001" / session / "decoded_1.root").exists()
                )
                stored = json.loads((controller.base / session / "config.json").read_text())
                raw_dir = Path(stored["raw_dir"])
                self.assertTrue((raw_dir / "manifest.json").exists())
                decoder_pid = (raw_dir / "decode_process.json").read_text()
                first_manifest = (raw_dir / "manifest.json").stat().st_mtime_ns
                again = controller.start(dict(run=1, live=False))
                self.assertEqual(again["cache"]["mode"], "reused")
                self.assertEqual(again["cache"]["directory"], str(raw_dir))
                deadline = time.monotonic() + 60
                while again["processing"] and time.monotonic() < deadline:
                    time.sleep(0.1)
                    again = controller.status(again["session"])
                self.assertEqual(again["analysis"]["status"], "complete", again)
                self.assertEqual(again["analysis"]["plotted"], 20)
                self.assertEqual((raw_dir / "decode_process.json").read_text(), decoder_pid)
                self.assertEqual((raw_dir / "manifest.json").stat().st_mtime_ns, first_manifest)
                config.update(matching=True, plot_name="matched_1.root")
                matched = controller.start(dict(run=1, live=False))
                self.assertEqual(matched["cache"]["mode"], "reused")
                deadline = time.monotonic() + 60
                while matched["processing"] and time.monotonic() < deadline:
                    time.sleep(0.1)
                    matched = controller.status(matched["session"])
                self.assertEqual(matched["decode"]["status"], "complete", matched)
                self.assertEqual(matched["decode"]["committed"], 12)
                self.assertEqual(matched["analysis"]["status"], "complete", matched)
                self.assertEqual(matched["analysis"]["plotted"], 10)
                self.assertEqual((raw_dir / "decode_process.json").read_text(), decoder_pid)
                config.update(matching=False, plot_name="decoded_1.root")
                live = controller.start(dict(run=1, live=True))
                self.assertEqual(live["cache"]["mode"], "seeded", live)
                live_raw = Path(live["cache"]["directory"])
                deadline = time.monotonic() + 60
                while not (live_raw / "manifest.json").exists() and time.monotonic() < deadline:
                    time.sleep(0.1)
                manifest = json.loads((live_raw / "manifest.json").read_text())
                self.assertEqual(manifest["events"], 24)
                name = manifest["chunks"][0]["name"]
                self.assertEqual((live_raw / name).stat().st_ino, (raw_dir / name).stat().st_ino)
                for mid in (41, 42):
                    with (directory / f"Run_00001_BIC_{mid}.dat").open("ab") as stream:
                        stream.write(packet(12, mid=mid))
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    live = controller.status(live["session"])
                    if live["decode"].get("decoded_records") == 26:
                        break
                    time.sleep(0.1)
                self.assertEqual(live["decode"].get("decoded_records"), 26, live)
                controller.stop(live["session"])
                deadline = time.monotonic() + 20
                while controller.alive(live_raw, "decode") and time.monotonic() < deadline:
                    time.sleep(0.1)
                final = controller.start(dict(run=1, live=False))
                self.assertEqual(final["cache"]["mode"], "seeded", final)
                deadline = time.monotonic() + 60
                while final["processing"] and time.monotonic() < deadline:
                    time.sleep(0.1)
                    final = controller.status(final["session"])
                self.assertEqual(final["decode"]["status"], "complete", final)
                self.assertEqual(final["decode"]["decoded_records"], 26, final)
                self.assertEqual(final["analysis"]["status"], "complete", final)
            finally:
                for process in controller.children:
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=10)
                    except Exception:
                        process.kill()
                        process.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
