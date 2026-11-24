"""Reading 100% must not imply that matching or plotting has completed."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from processing.input_progress import input_progress
from processing.event_pipeline import Pipeline
from test_live import packet


class ProgressTests(unittest.TestCase):
    def test_weighted_bytes_missing_and_growing_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a"
            b = Path(tmp) / "b"
            a.write_bytes(b"a" * 100)
            b.write_bytes(b"b" * 300)
            inputs = [dict(path=str(a), bytes=100), dict(path=str(b), bytes=100)]
            p = input_progress(inputs)
            self.assertEqual(p["percent"], 50)
            self.assertEqual(p["files_read"], 1)
            self.assertFalse(p["complete"])
            inputs[1]["bytes"] = 300
            self.assertTrue(input_progress(inputs)["complete"])
            b.write_bytes(b"b" * 700)
            self.assertEqual(input_progress(inputs)["percent"], 50)
            b.unlink()
            p = input_progress(inputs)
            self.assertIsNone(p["percent"])
            self.assertEqual(p["missing_files"], 1)
            self.assertFalse(p["complete"])
            self.assertIsNone(input_progress([]))

    def test_read_complete_with_decoded_queue_still_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "Run_00001_BIC_41.dat").write_bytes(packet(1, mid=41) + packet(2, mid=41))
            config = dict(
                matching=False,
                decode_batch_size=1,
                run=1,
                mapping=[dict(name="A", daq="BIC", mid=41, ch=1)],
                capture=["A"],
                required=["A"],
                nk_path=tmp,
                rc_path=tmp,
                reorder=0,
                queue_limit=4000,
                clock_scale=1.0,
                tolerance_us=1.0,
            )
            p = Pipeline(config)
            phases = []
            p.step(final=True, report=phases.append)
            snapshot = p.snapshot("running")
            self.assertEqual(phases, ["reading", "collecting"])
            self.assertEqual(snapshot["input_progress"]["percent"], 100)
            self.assertEqual(snapshot["status"], "running")
            self.assertFalse(p.exhausted())
            self.assertEqual(snapshot["decoded_records"], 1)


if __name__ == "__main__":
    unittest.main()
