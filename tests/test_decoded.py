"""No-cut inputs must not be intersected, synchronized or share event limits."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_live import packet
from matching.timestamp_matcher import TimeMatcher
from storage.event_data import Event, Wave
from processing.event_pipeline import Pipeline
from storage.root_writer import write_chunk
from plotting.cpp_plotter import Plots
from plot_helpers import histogram, waveform_counts
from processing.execution_plan import prepare


class DecodedTests(unittest.TestCase):
    def test_plan_matches_same_event_jobs_not_channel_count(self):
        for profile in ("NKDAQ", "RCDAQ"):
            for aux in (False, True):
                for mode in ("none", "dwc", "dwc_pid"):
                    p = prepare(
                        dict(
                            profile=profile,
                            run=1086,
                            type="full",
                            method="IntADC",
                            aux=aux,
                            aux_cut_mode=mode,
                        ),
                        {"DQM_DATA_PATH": "/nk", "RCDAQ_DATA_PATH": "/rc"},
                    )
                    self.assertEqual(p["config"]["matching"], mode != "none" or aux)
                    if mode == "none" and not aux:
                        self.assertIsNone(p["config"]["reference"])
                    self.assertEqual(bool(p["config"]["matching_reasons"]), mode != "none" or aux)

    def test_mixed_pipeline_keeps_timing_across_decode_batches(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            rows = [
                dict(name="A", daq="BIC", mid=41, ch=1),
                dict(name="R", daq="GCROC", mid=-1, ch=139),
            ]
            config = dict(
                matching=True,
                timing=True,
                run=1,
                mapping=rows,
                capture=["A", "R"],
                required=["A", "R"],
                reference=None,
                nk_path=tmp,
                rc_path=tmp,
                reorder=0,
                queue_limit=4000,
                clock_scale=1.0,
                offset_us=-13.0,
                tolerance_us=1.0,
            )
            (d / "Run_00001_BIC_41.dat").write_bytes(
                b"".join(packet(i, mid=41) for i in range(900))
            )
            p = Pipeline(config)
            p.rc_path.write_bytes(b"x")
            p.channel_vector = [139]
            waves = [
                SimpleNamespace(
                    timestamp=(100 * i + 13) * 160,
                    samples=20,
                    adc=[100] * 20,
                    toa=[i % 1024] * 20,
                    tot=[3] * 20,
                )
                for i in range(1200)
            ]
            p.decode = lambda path, offset, *args: SimpleNamespace(
                next=1,
                events=1 if offset == 0 else 0,
                endRun=True,
                waves=waves if offset == 0 else [],
            )
            results = []
            decoded = []
            for _ in range(10):
                p.step(True)
                if p.batch_decoded == 1000 or p.exhausted():
                    decoded.append(p.batch_decoded)
                    results.extend(p.pending)
                    p.pending = []
                    p.batch_decoded = 0
                if p.exhausted():
                    break
            else:
                self.fail("Pipeline did not finish")
            self.assertEqual(decoded, [1000, 1000, 100])
            self.assertEqual(p.decoded_total, 2100)
            self.assertEqual([e.key for e in results], list(range(900)))
            self.assertTrue(all(set(e.waves) == {"A", "R"} for e in results))
            self.assertEqual(list(results[899].waves["R"].toa), [899] * 20)
            self.assertEqual(p.matcher.dropped_rc, 300)

    def test_disjoint_triggers_survive_and_limits_are_per_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            rows = [
                dict(
                    name=f"Bulk{i}_xp_y0",
                    module=f"Bulk{i}",
                    daq="BIC",
                    mid=40 + i,
                    ch=1,
                    det=1,
                    side=1,
                    z=i - 1,
                    y=0,
                    sma=i,
                )
                for i in (1, 2)
            ]
            config = dict(
                matching=False,
                run=1,
                profile="NKDAQ",
                mapping=rows,
                capture=[r["name"] for r in rows],
                required=[r["name"] for r in rows],
                reference=None,
                nk_path=tmp,
                rc_path=tmp,
                reorder=0,
                queue_limit=10,
                clock_scale=1.0,
                tolerance_us=1.0,
                calibration={},
                plot_dir=tmp,
                plot_name="decoded_1.root",
            )
            (d / "Run_00001_BIC_41.dat").write_bytes(packet(0, mid=41) + packet(2, mid=41))
            (d / "Run_00001_BIC_42.dat").write_bytes(packet(1, mid=42) + packet(3, mid=42))
            p = Pipeline(config)
            with patch.object(
                p.join, "drain", side_effect=AssertionError("No NK matching")
            ), patch.object(p.matcher, "drain", side_effect=AssertionError("No clock matching")):
                p.step()
            self.assertEqual([e.key for e in p.pending], [0, 1, 2, 3])
            self.assertEqual([e.source_event for e in p.pending], [0, 0, 1, 1])
            name = write_chunk(d, 0, p.pending, 0, config)
            analysis = dict(
                type="full",
                method="IntADC",
                revision=1,
                cuts=[],
                count=1,
                first=0,
                jobs=[dict(executable="draw_intADC", channels=config["required"])],
            )
            plots = Plots(config, analysis)
            plots.add(d / name)
            self.assertEqual(histogram(plots, rows[0]["name"], "IntADC").GetEntries(), 1)
            self.assertEqual(histogram(plots, rows[1]["name"], "IntADC").GetEntries(), 1)
            # The same input with cuts uses the existing intersection join.
            matched = Pipeline(dict(config, matching=True))
            matched.step(True)
            self.assertEqual(matched.pending, [])

    def test_limit_uses_available_channel_entries_not_file_ordinals(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [
                dict(
                    name=f"Bulk{i}_xp_y0",
                    module=f"Bulk{i}",
                    daq="BIC",
                    mid=41,
                    ch=i,
                    det=1,
                    side=1,
                    z=i - 1,
                    y=0,
                    sma=i,
                )
                for i in (1, 2)
            ]
            config = dict(matching=False, run=1, mapping=rows, calibration={}, plot_dir=tmp)
            events = []
            for i in range(110):
                waves = {rows[0]["name"]: Wave(i, i, np.full(64, 10, dtype=np.int16))}
                if i >= 20:
                    waves[rows[1]["name"]] = Wave(i, i, np.full(64, 20, dtype=np.int16))
                events.append(Event(i, i, waves, source="BIC:41", source_event=i))
            path = Path(tmp) / write_chunk(Path(tmp), 0, events, 0, config)
            channels = [r["name"] for r in rows]
            for method in ("IntADC", "Waveform"):
                jobs = [
                    dict(
                        executable="draw_intADC" if method == "IntADC" else "draw_waveform",
                        channels=channels,
                    )
                ]
                if method == "IntADC":
                    jobs.insert(0, dict(executable="draw_heatmap", channels=channels))
                a = dict(
                    type="full", method=method, revision=1, cuts=[], count=100, first=0, jobs=jobs
                )
                plots = Plots(config, a)
                plots.add(path)
                if method == "IntADC":
                    self.assertEqual(
                        [histogram(plots, n, method).GetEntries() for n in channels], [100, 90]
                    )
                else:
                    self.assertEqual(waveform_counts(plots, channels), [100, 90])
            p = prepare(
                dict(
                    profile="NKDAQ",
                    run=1,
                    type="single",
                    method="Waveform",
                    channels="SFIL6_xm_y2",
                    count="",
                ),
                {"DQM_DATA_PATH": "/nk", "RCDAQ_DATA_PATH": "/rc"},
            )
            self.assertEqual(p["analysis"]["count"], -1)

    def test_matched_timing_survives_join_root_and_aux_cut(self):
        row = dict(
            name="SFIL6_xm_y2",
            module="SFIL6",
            daq="GCROC",
            mid=-1,
            ch=139,
            det=0,
            side=0,
            z=2,
            y=2,
            sma=0,
        )
        cc = dict(
            name="CC1", module=None, daq="NKFADC", mid=2, ch=1, det=-1, side=-1, z=-1, y=-1, sma=-1
        )
        for matching in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                config = dict(
                    matching=matching, run=1, mapping=[row, cc], calibration={}, plot_dir=tmp
                )
                m = TimeMatcher(scale=1, offset=0)
                m.nk.append(Event(1, 10, {"CC1": Wave(1, 10, np.full(40, 100, dtype=np.int16))}))
                m.rc.append(
                    Event(
                        1,
                        10,
                        rc_adc=np.full((1, 20), 100, dtype=np.int16),
                        rc_names=(row["name"],),
                        rc_toa=np.array([[999, 1, 1, 1023] + [0] * 16], dtype=np.int16),
                        rc_tot=np.array([[999, 3, 3, 1023] + [0] * 16], dtype=np.int16),
                    )
                )
                events = m.drain()
                self.assertEqual(len(events), 1)
                name = write_chunk(Path(tmp), 0, events, 0, config)
                for method in ("TOA", "TOT"):
                    analysis = dict(
                        type="single",
                        method=method,
                        revision=1,
                        cuts=[dict(field="CC1.peak", max=10)] if matching else [],
                        count=-1,
                        first=0,
                        jobs=[dict(executable="draw_" + method.lower(), channels=[row["name"]])],
                    )
                    plots = Plots(config, analysis)
                    plots.add(Path(tmp) / name)
                    self.assertEqual(histogram(plots, row["name"], method).GetEntries(), 3)
                if matching:
                    events[0].waves["CC1"].adc[35] = 50  # baseline - ADC peak = 50: fail CC < 10
                    name = write_chunk(Path(tmp), 1, events, 0, config)
                    rejected = Plots(config, analysis)
                    rejected.add(Path(tmp) / name)
                    self.assertEqual(histogram(rejected, row["name"], "TOT").GetEntries(), 0)
