import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from decoding.nkdaq_reader import NKTail
from matching.trigger_matcher import NKJoin
from matching.timestamp_matcher import TimeMatcher
from storage.event_data import Wave, Event
from reference_metrics import pulse, arrays
from processing.event_cuts import passes
from processing.execution_plan import prepare


def packet(key, ch=1, mid=42, daq="BIC", samples=None):
    samples = np.array(samples if samples is not None else [10] * 64, dtype="<i2")
    if daq == "BIC":
        samples = np.column_stack((samples, np.zeros_like(samples))).ravel()
    body = samples.tobytes()
    h = bytearray(32)
    h[:4] = (32 + len(body)).to_bytes(4, "little")
    h[7:11] = key.to_bytes(4, "little")
    h[15] = mid
    h[16] = ch
    h[26:32] = (key * 100).to_bytes(6, "little")
    return bytes(h) + body


class IncrementalTests(unittest.TestCase):
    def test_fragmented_record_and_checkpoint_offsets(self):
        data = b"".join(packet(k) for k in range(25))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "growing.dat"
            path.touch()
            tail = NKTail(path, "BIC", 42, {1: "A"}, 2)
            for start in range(0, len(data), 37):
                with path.open("ab") as f:
                    f.write(data[start : start + 37])
                before = tail.offset
                tail.poll()
                self.assertLessEqual(tail.offset, path.stat().st_size)
            tail.finish()
            self.assertEqual([e.key for e in tail.ready], list(range(25)))
            self.assertEqual(tail.offset, len(data))
            self.assertEqual(tail.poll(), 0)
            path.write_bytes(b"")
            with self.assertRaisesRegex(RuntimeError, "truncated"):
                tail.poll()

    def test_multichannel_out_of_order_and_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "data"
            path.write_bytes(
                packet(0, 1) + packet(1, 1) + packet(0, 2) + packet(2, 1) + packet(2, 2)
            )
            tail = NKTail(path, "BIC", 42, {1: "A", 2: "B"}, 3)
            tail.poll()
            tail.finish()
            join = NKJoin(["A", "B"])
            self.assertEqual([e.key for e in join.drain([tail], True)], [0, 2])
            self.assertEqual(join.dropped, 1)

    def test_fadc_fixed_length_bad_lane_and_partial_block(self):
        lanes = [packet(5, ch=i + 1, mid=1, daq="NKFADC") for i in range(4)]
        data = bytes(v for group in zip(*lanes) for v in group)
        corrupted = bytearray(data)
        corrupted[0] = 99  # corrupt only first lane length
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fadc"
            path.write_bytes(data + corrupted[:-1])
            tail = NKTail(path, "NKFADC", 1, {4: "TRIG2"}, 0)
            tail.poll()
            self.assertEqual(tail.offset, len(data))
            self.assertEqual(len(tail.ready), 1)
            with path.open("ab") as f:
                f.write(corrupted[-1:])
            tail.poll()
            self.assertEqual(tail.offset, len(data) * 2)
            self.assertEqual(tail.bad, 1)

    def test_nk_join_uses_trigger_not_position(self):
        from types import SimpleNamespace
        from collections import deque

        a = SimpleNamespace(
            ready=deque(Event(k, k, {"A": Wave(k, k, np.array([1]))}) for k in [0, 1, 3])
        )
        b = SimpleNamespace(
            ready=deque(Event(k, k, {"B": Wave(k, k, np.array([1]))}) for k in [1, 2, 3])
        )
        self.assertEqual([e.key for e in NKJoin(["A", "B"]).drain([a, b], True)], [1, 3])


class MatchingTests(unittest.TestCase):
    def test_sync_missing_events_and_growing_batches(self):
        rng = np.random.default_rng(3)
        t = np.cumsum(rng.uniform(200, 20000, 200))
        scale = 0.99998982
        offset = 12345.6
        m = TimeMatcher()
        m.nk.extend(
            Event(i, float(x * scale + offset)) for i, x in enumerate(t) if i not in [2, 39]
        )
        m.rc.extend(
            Event(i, float(x), rc_timestamp=int(x * 160))
            for i, x in enumerate(t)
            if i not in [0, 9]
        )
        out = m.drain()
        self.assertTrue(m.locked)
        self.assertEqual([e.key for e in out], [i for i in range(200) if i not in [0, 2, 9, 39]])
        self.assertTrue(all(abs(e.delta) < 1e-6 for e in out))

    def test_ambiguous_periodic_sync_rejected(self):
        m = TimeMatcher(scale=1)
        m.nk.extend(Event(i, i * 100.0) for i in range(150))
        m.rc.extend(Event(i, i * 100.0) for i in range(150))
        self.assertEqual(m.drain(), [])
        self.assertFalse(m.locked)

    def test_clock_refinement_across_spill_gap(self):
        t = np.cumsum(np.random.default_rng(7).uniform(40, 1000, 300))
        t[150:] += 5e6
        m = TimeMatcher()
        m.nk.extend(Event(i, float(x * 0.99998946 + 1234)) for i, x in enumerate(t))
        m.rc.extend(Event(i, float(x)) for i, x in enumerate(t))
        out = m.drain()
        self.assertEqual(len(out), len(t))
        self.assertAlmostEqual(m.scale, 0.99998946, places=9)

    def test_dense_rc_queue_preserves_waveform(self):
        m = TimeMatcher(scale=1, offset=10)
        raw = np.arange(40, dtype=np.int16).reshape(2, 20)
        m.nk.append(Event(7, 110, {"NK": Wave(7, 110, np.ones(20, dtype=np.int16))}))
        m.rc.append(Event(0, 100, {}, 16000, rc_adc=raw, rc_names=("RC1", "RC2")))
        import pickle

        m = pickle.loads(pickle.dumps(m))
        event = m.drain()[0]
        self.assertEqual(event.key, 7)
        np.testing.assert_array_equal(event.waves["RC2"].adc, raw[1])
        self.assertIn("NK", event.waves)

    def test_verified_offset_and_tolerance(self):
        m = TimeMatcher(scale=1, offset=10, tolerance=1)
        m.nk.extend([Event(0, 110), Event(1, 211.1)])
        m.rc.extend([Event(0, 100), Event(1, 200)])
        self.assertEqual(len(m.drain()), 1)


class MetricsTests(unittest.TestCase):
    def test_gcroc_adc_baseline_and_raw_preserved(self):
        wave = np.array([999] + [100] * 4 + [150] + [100] * 14, dtype=np.int16)
        before = wave.copy()
        valid, baseline, peak, integral = pulse(wave, "GCROC")
        self.assertEqual((valid, baseline, peak, integral), (True, 100, 50, 50))
        np.testing.assert_array_equal(wave, before)
        self.assertFalse(pulse(wave[:19], "GCROC")[0])

    def test_cut_missing_channel_and_boundaries(self):
        cuts = [dict(field="CC1.peak", min=20, max=40)]
        self.assertTrue(passes(cuts, {"CC1": 0}, [1], [20], [0], [math.nan] * 6))
        self.assertFalse(passes(cuts, {"CC1": 0}, [0], [30], [0], [math.nan] * 6))
        self.assertFalse(passes([dict(field="DWC1.x", min=-10)], {}, [], [], [], [math.nan] * 6))

    def test_plan_mapping_dependency_and_invalid_cut(self):
        env = {"DQM_DATA_PATH": "/nk", "RCDAQ_DATA_PATH": "/rc"}
        req = dict(
            profile="RCDAQ",
            run=1086,
            type="single",
            method="Avg",
            channels="SFIL6_xm_y2",
            cuts=[dict(field="CC1.peak", min=20)],
        )
        p = prepare(req, env)
        self.assertEqual(p["config"]["reference"], "TRIG2")
        self.assertIn("CC1", p["config"]["capture"])
        self.assertNotIn("HODO_L_01", p["config"]["capture"])
        with self.assertRaises(ValueError):
            prepare(dict(req, cuts=[dict(field="CC1.peak", min=100, max=20)]), env)

    def test_dwc_correlation_cuts_and_dependencies(self):
        cuts = [dict(field="DWC.dx", max=5), dict(field="DWC.dy", max=5)]
        self.assertTrue(passes(cuts, {}, [], [], [], [1, 2, 6, -3, 0, 0]))
        self.assertFalse(passes(cuts, {}, [], [], [], [1, 2, 7, -3, 0, 0]))
        self.assertFalse(passes(cuts, {}, [], [], [], [1, 2, 6, math.nan, 0, 0]))
        env = {"DQM_DATA_PATH": "/nk", "RCDAQ_DATA_PATH": "/rc"}
        req = dict(
            profile="RCDAQ",
            run=1086,
            type="single",
            method="Avg",
            channels="SFIL6_xm_y2",
            cuts=cuts,
        )
        plan = prepare(req, env)
        for d in ("DWC1", "DWC2"):
            for side in "LRUD":
                self.assertIn(d + "_" + side, plan["config"]["required"])
        self.assertEqual(plan["config"]["reference"], "TRIG2")
        for name in ("PS", "MC"):
            with self.assertRaisesRegex(ValueError, "Unknown cut field"):
                prepare(dict(req, cuts=[dict(field=name + ".peak", min=1)]), env)

    def test_native_metrics_match_reference_and_flat_dwc(self):
        from storage.root_writer import root, write_chunk

        rows = [
            dict(name=n, daq=q, mid=1, ch=i + 1, det=-1, side=-1, z=-1, y=-1, sma=-1)
            for i, (n, q) in enumerate(
                [
                    ("DWC1_L", "NKFADC"),
                    ("DWC1_R", "NKFADC"),
                    ("DWC1_U", "NKFADC"),
                    ("DWC1_D", "NKFADC"),
                    ("GC", "GCROC"),
                    ("BIC", "BIC"),
                    ("HODO_L_01", "JBNU"),
                ]
            )
        ]
        calib = dict(DWC1_X_SLOPE=1.0, DWC1_X_OFFSET=0.0, DWC1_Y_SLOPE=1.0, DWC1_Y_OFFSET=0.0)
        config = dict(mapping=rows, calibration=calib)
        events = []
        expected = []
        rng = np.random.default_rng(42)
        for k in range(20):
            waves = {}
            for r in rows:
                a = (
                    np.full(64, 2000, dtype=np.int16)
                    if k == 0
                    else rng.integers(1800, 2010, size=64, dtype=np.int16)
                )
                if r["daq"] == "GCROC":
                    a = np.full(20 if k % 2 else 19, 100, dtype=np.int16)
                if r["daq"] == "BIC" and k == 0:
                    a[:] = 0
                waves[r["name"]] = Wave(k, k * 100, a)
            e = Event(k, k * 100, waves)
            events.append(e)
            expected.append(arrays(e, rows, calib))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            name = write_chunk(path, 0, events, 0, config)
            f = root().TFile.Open(str(path / name))
            for k, e in enumerate(f.Get("event_tree")):
                for branch, column in [
                    ("baseline", 4),
                    ("peak", 5),
                    ("integral", 6),
                    ("derived", 9),
                ]:
                    np.testing.assert_allclose(
                        np.asarray(getattr(e, branch)),
                        expected[k][column],
                        atol=1e-8,
                        equal_nan=True,
                    )
                if k == 0:
                    self.assertTrue(math.isnan(e.derived[0]))
            f.Close()

    def test_root_schema_round_trip(self):
        from storage.root_writer import root, write_chunk

        row = dict(name="A", daq="BIC", mid=42, ch=1, det=0, side=0, z=0, y=0, sma=0)
        config = dict(mapping=[row], calibration={})
        wave = np.arange(64, dtype=np.int16)
        event = Event(17, 123, {"A": Wave(17, 123, wave)})
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            name = write_chunk(d, 0, [event], 0, config)
            f = root().TFile.Open(str(d / name))
            t = f.Get("event_tree")
            self.assertEqual(t.GetEntries(), 1)
            t.GetEntry(0)
            self.assertEqual(int(t.nk_trigger), 17)
            self.assertEqual(int(t.triggers[0]), 17)
            np.testing.assert_array_equal(np.asarray(t.adc), wave)
            self.assertEqual(list(t.offsets), [0, 64])
            f.Close()
            self.assertFalse(list(d.glob("*.partial")))


if __name__ == "__main__":
    unittest.main()
