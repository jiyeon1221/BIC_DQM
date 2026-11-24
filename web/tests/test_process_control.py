"""Actual process discovery and shutdown across simultaneous DQM sessions."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from processing import session_manager as control


class ProcessControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for folder in ("processing", "plotting"):
            (self.root / folder).mkdir()
        script = """import os,signal,sys,time
from pathlib import Path
if os.getenv('DQM_TEST_IGNORE_TERM'):signal.signal(signal.SIGTERM,signal.SIG_IGN)
(Path(sys.argv[1])/(Path(__file__).parent.name+'.ready')).touch()
while True:time.sleep(.1)
"""
        for folder, name in (("processing", "run_processing.py"), ("plotting", "run_plotting.py")):
            (self.root / folder / name).write_text(script)
        self.root_patch = patch.object(control, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.c = control.Controller(dict(os.environ), self.root / "plots")
        self.extra = []
        self.addCleanup(self.cleanup_processes)

        def plan(request):
            return dict(
                config=dict(profile="NKDAQ", run=request["run"], matching=False),
                analysis=dict(revision=1),
            )

        self.c.plan = plan

    def cleanup_processes(self):
        for p in self.c.children + self.extra:
            if p.poll() is None:
                p.kill()
            p.wait(timeout=10)

    def start(self, run):
        result = self.c.start(dict(run=run, live=True))
        d = self.c.base / result["session"]
        deadline = time.monotonic() + 10
        config = control.read(d / "config.json")
        raw = Path(config["raw_dir"])
        while not ((raw / "processing.ready").exists() and (d / "plotting.ready").exists()):
            if time.monotonic() > deadline:
                self.fail("Workers did not start")
            time.sleep(0.02)
        return result["session"]

    def test_all_sessions_found_after_metadata_cleanup_and_restart(self):
        first = self.start(1)
        second = self.start(2)
        found = self.c.processes()
        self.assertEqual(len(found), 4)
        self.assertEqual({p["session"] for p in found if p["kind"] == "analysis"}, {first, second})
        self.assertEqual({p["run"] for p in found}, {1, 2})
        # An unrelated Python process must never become a kill target, even if
        # stale PID metadata accidentally points at it.
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        self.extra.append(other)
        control.write(self.c.base / first / "decode_process.json", dict(pid=other.pid))
        (self.c.base / "active.json").unlink()
        shutil.rmtree(self.c.base / first)
        restarted = control.Controller(dict(os.environ), self.root / "plots")
        found = restarted.processes()
        self.assertEqual(len(found), 4)
        self.assertNotIn(other.pid, [p["pid"] for p in found])
        result = restarted.stop_all(timeout=2)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["killed_count"], 4)
        self.assertEqual(restarted.processes(), [])
        self.assertIsNone(other.poll())

    def test_pid_identity_rechecked_and_unresponsive_workers_stopped(self):
        self.c.env["DQM_TEST_IGNORE_TERM"] = "1"
        self.start(3)
        found = self.c.processes()
        self.assertEqual(len(found), 2)
        fake = dict(found[0], start_ticks="not-the-same-process")
        self.assertFalse(self.c.signal_process(fake, 15))
        self.assertIsNotNone(self.c.process(fake["pid"]))
        result = self.c.stop_all(timeout=0.1)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["killed_count"], 2)

    def test_shared_live_decoder_survives_stopping_one_plot(self):
        first = self.start(7)
        second = self.start(7)
        self.assertEqual(len(self.c.processes()), 3)
        raw = Path(control.read(self.c.base / first / "config.json")["raw_dir"])
        self.c.stop(first)
        deadline = time.monotonic() + 5
        while self.c.alive(self.c.base / first, "analysis") and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(self.c.alive(raw, "decode"))
        self.assertTrue(self.c.alive(self.c.base / second, "analysis"))
        result = self.c.stop_all(timeout=2)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["killed_count"], 2)

    def test_relative_script_paths_without_pid_files(self):
        session = "f" * 16
        d = self.c.base / session
        d.mkdir()
        proc = subprocess.Popen(
            [sys.executable, "processing/run_processing.py", str(d.relative_to(self.root))],
            cwd=self.root,
        )
        self.extra.append(proc)
        deadline = time.monotonic() + 10
        while not (d / "processing.ready").exists():
            if time.monotonic() > deadline:
                self.fail("Worker did not start")
            time.sleep(0.02)
        found = self.c.processes()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["pid"], proc.pid)
        result = self.c.stop_all(timeout=2)
        self.assertTrue(result["success"], result)


if __name__ == "__main__":
    unittest.main()
