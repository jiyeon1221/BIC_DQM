"""Process-level append/pause/resume test; ROOT and the LCG environment are required."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_live import packet
from storage.root_writer import root


class StreamingTest(unittest.TestCase):
    def test_live_publishes_by_decode_count_before_matching(self):
        # Check that 1,000 decoded records publish 250 common trigger pairs immediately.
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            config = self.two_inputs(d)
            (d / "Run_00001_BIC_41.dat").write_bytes(
                b"".join(packet(i, mid=41) for i in range(1000))
            )
            (d / "Run_00001_BIC_42.dat").write_bytes(
                b"".join(packet(2 * i, mid=42) for i in range(1000))
            )
            (d / "config.json").write_text(json.dumps(config))
            with (d / "test.log").open("w") as log:
                proc = subprocess.Popen(
                    [
                        sys.executable,
                        str(Path(__file__).resolve().parents[1] / "processing/run_processing.py"),
                        str(d),
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                try:
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline:
                        self.assertIsNone(proc.poll(), (d / "test.log").read_text())
                        try:
                            manifest = json.loads((d / "manifest.json").read_text())
                        except FileNotFoundError:
                            manifest = {}
                        if manifest.get("decoded", 0) >= 2000:
                            break
                        time.sleep(0.1)
                    else:
                        self.fail((d / "test.log").read_text())
                    self.assertEqual([c["decoded_until"] for c in manifest["chunks"]], [1000, 2000])
                    self.assertEqual([c["entries"] for c in manifest["chunks"]], [250, 250])
                    self.assertEqual(manifest["events"], 500)
                    self.assertEqual(manifest["decode_batches"], 2)
                    # EOF is not completion in Live.
                    self.assertIsNone(proc.poll())
                    proc.send_signal(signal.SIGTERM)
                    proc.wait(20)
                    self.assertEqual(proc.returncode, 0, (d / "test.log").read_text())
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait()

    def test_batch_consumes_long_tail_after_short_source_ends(self):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            config = self.two_inputs(d)
            config["queue_limit"] = 1200
            (d / "config.json").write_text(json.dumps(config))
            (d / "Run_00001_BIC_41.dat").write_bytes(
                b"".join(packet(i, mid=41) for i in range(6000))
            )
            (d / "Run_00001_BIC_42.dat").write_bytes(b"".join(packet(i, mid=42) for i in range(90)))
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "processing/run_processing.py"),
                    str(d),
                    "--finite",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((d / "manifest.json").read_text())
            self.assertEqual(manifest["events"], 90)
            self.assertEqual(manifest["decoded"], 6090)
            self.assertEqual(manifest["decode_batches"], 7)
            self.assertEqual(
                json.loads((d / "decode_status.json").read_text())["status"], "complete"
            )

    @staticmethod
    def two_inputs(directory):
        rows = [
            dict(name=name, daq="BIC", mid=mid, ch=1, det=0, side=0, z=0, y=0, sma=0)
            for name, mid in [("A", 41), ("B", 42)]
        ]
        return dict(
            schema=3,
            matching=True,
            run=1,
            profile="NKDAQ",
            mapping=rows,
            capture=["A", "B"],
            required=["A", "B"],
            reference=None,
            nk_path=str(directory),
            rc_path=str(directory),
            reorder=0,
            queue_limit=4000,
            clock_scale=1.0,
            tolerance_us=1.0,
            offset_us=None,
            calibration={},
        )

    def test_append_pause_resume_and_final_chunk(self):
        self.check_stream(True)

    def test_independent_decode_append_pause_resume(self):
        self.check_stream(False)

    def check_stream(self, matching):
        R = root()
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            raw = d / "Run_00001_BIC_42.dat"
            row = dict(name="A", daq="BIC", mid=42, ch=1, det=0, side=0, z=0, y=0, sma=0)
            config = dict(
                schema=2,
                matching=matching,
                run=1,
                profile="NKDAQ",
                mapping=[row],
                capture=["A"],
                required=["A"],
                reference=None,
                nk_path=temp,
                rc_path=temp,
                reorder=2,
                queue_limit=12000,
                clock_scale=1.0,
                tolerance_us=1.0,
                offset_us=None,
                calibration={},
            )
            (d / "config.json").write_text(json.dumps(config))
            data = b"".join(packet(i) for i in range(2107))
            size = len(packet(0))
            raw.write_bytes(data[: size * 1005 + 17])
            argv = [
                sys.executable,
                str(Path(__file__).resolve().parents[1] / "processing/run_processing.py"),
                str(d),
            ]
            log = (d / "test.log").open("w")
            proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)

            def wait_events(target):
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        self.fail((d / "test.log").read_text())
                    try:
                        manifest = json.loads((d / "manifest.json").read_text())
                    except FileNotFoundError:
                        manifest = {}
                    if manifest.get("events", 0) >= target:
                        return manifest
                    time.sleep(0.1)
                self.fail("Timed out: " + (d / "test.log").read_text())

            try:
                self.assertEqual(wait_events(1000)["events"], 1000)
                proc.send_signal(signal.SIGTERM)
                proc.wait(20)
                self.assertEqual(proc.returncode, 0)
                paused = json.loads((d / "decode_status.json").read_text())
                self.assertEqual(paused["status"], "paused")
                self.assertEqual(paused["inputs"][0]["bytes"], size * 1005)
                with raw.open("ab") as f:
                    f.write(data[size * 1005 + 17 :])
                proc = subprocess.Popen(argv + ["--finite"], stdout=log, stderr=subprocess.STDOUT)
                proc.wait(60)
                self.assertEqual(proc.returncode, 0, (d / "test.log").read_text())
                manifest = json.loads((d / "manifest.json").read_text())
                self.assertEqual(manifest["events"], 2107)
                keys = []
                ordinals = []
                for chunk in manifest["chunks"]:
                    self.assertLessEqual(chunk["entries"], 1000)
                    f = R.TFile.Open(str(d / chunk["name"]))
                    t = f.Get("event_tree")
                    self.assertEqual(t.GetEntries(), chunk["entries"])
                    for e in t:
                        keys.append(int(e.nk_trigger))
                        ordinals.append(int(e.event))
                        self.assertEqual(int(e.adc[0]), 10)
                    f.Close()
                self.assertEqual(keys, list(range(2107)))
                self.assertEqual(ordinals, list(range(2107)))
                self.assertEqual(
                    json.loads((d / "decode_status.json").read_text())["status"], "complete"
                )
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                log.close()


if __name__ == "__main__":
    unittest.main()
