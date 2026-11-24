"""GCROC timing selection and h2gcroc 2D sample histogram semantics."""
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from processing.execution_plan import prepare
from plotting.cpp_plotter import Plots
from plot_helpers import histogram
from storage.event_data import Event, Wave
from storage.root_writer import write_chunk, root


class TimingTests(unittest.TestCase):
    def plan(self, **changes):
        request = dict(
            profile="RCDAQ",
            run=1088,
            type="single",
            method="TOA",
            channels="SFIL6_xm_y2",
            aux=False,
            aux_cut_mode="none",
        )
        request.update(changes)
        return prepare(request, {"DQM_DATA_PATH": "/nk", "RCDAQ_DATA_PATH": "/rc"})

    def test_direct_source_and_restricted_selection(self):
        for method in ("TOA", "TOT", "TOA/TOT"):
            p = self.plan(method=method)
            self.assertFalse(p["config"]["matching"])
            self.assertIsNone(p["config"]["reference"])
            self.assertTrue(p["config"]["timing"])
            self.assertEqual(p["analysis"]["cuts"], [])
            matched = self.plan(method=method, aux_cut_mode="dwc_pid", aux=True)
            self.assertTrue(matched["config"]["matching"])
            self.assertEqual(matched["config"]["reference"], "TRIG2")
            for changes in [dict(profile="NKDAQ"), dict(type="module"), dict(channels="CC1")]:
                with self.assertRaises(ValueError):
                    self.plan(method=method, **changes)

    def test_h2gcroc_selection_axes_and_long_waveforms(self):
        for method in ("TOA", "TOT"):
            with tempfile.TemporaryDirectory() as temp:
                p = self.plan(method=method)
                p["config"]["plot_dir"] = temp
                plots = Plots(p["config"], p["analysis"])
                values = np.array([999, 1, 0, 1023, 10] + [0] * 15, dtype=np.int16)

                def add_timing(number, codes):
                    wave = Wave(
                        number, number, np.full(len(codes), 100, dtype=np.int16), codes, codes
                    )
                    event = Event(
                        number, number, {"SFIL6_xm_y2": wave}, source="GCROC", source_event=number
                    )
                    name = write_chunk(Path(temp), number, [event], number, p["config"])
                    plots.add(Path(temp) / name)

                add_timing(0, values[:19])
                self.assertEqual(histogram(plots, "SFIL6_xm_y2", method).GetEntries(), 0)
                add_timing(1, values)
                # Check that positive timing values fill their sample bins, excluding sample zero.
                h = histogram(plots, "SFIL6_xm_y2", method)
                self.assertEqual(h.GetDimension(), 2)
                self.assertEqual(h.GetEntries(), 3)
                self.assertEqual(h.GetNbinsY(), 50)
                self.assertEqual(h.GetYaxis().GetXmin(), 1 if method == "TOA" else -100)
                self.assertEqual(h.GetYaxis().GetXmax(), 1024 if method == "TOA" else 4500)
                self.assertEqual(h.GetBinContent(h.FindBin(0, 999)), 0)
                for sample in (1, 3, 4):
                    self.assertEqual(h.GetBinContent(h.FindBin(sample, int(values[sample]))), 1)
                self.assertEqual(h.GetXaxis().GetLast(), 20)
                long = np.zeros(40, dtype=np.int16)
                long[39] = 500
                add_timing(2, long)
                h = histogram(plots, "SFIL6_xm_y2", method)
                self.assertEqual(h.GetXaxis().GetLast(), 40)
                self.assertEqual(h.GetBinContent(h.FindBin(39, 500)), 1)
                plots.save()
                f = root().TFile.Open(str(Path(temp) / p["config"]["plot_name"]))
                key = next(k for k in f.GetListOfKeys() if k.GetClassName() == "TCanvas")
                saved = f.Get(key.GetName()).GetPrimitive(f"h_SFIL6_xm_y2_{method}_1")
                self.assertEqual(saved.GetDimension(), 2)
                self.assertEqual(saved.GetEntries(), 4)
                self.assertEqual(saved.GetXaxis().GetTitle(), "Sample index")
                self.assertEqual(saved.GetZaxis().GetTitle(), "Counts")
                f.Close()

    def test_combined_selection_writes_two_distinct_canvases(self):
        from storage.event_data import Event, Wave
        from storage.root_writer import write_chunk

        names = ["SFIL6_xm_y2", "SFIL6_xp_y2"]
        for matching in (False, True):
            with self.subTest(matching=matching), tempfile.TemporaryDirectory() as temp:
                p = self.plan(method="TOA/TOT", channels=" ".join(names))
                config = p["config"]
                a = p["analysis"]
                config.update(plot_dir=temp, matching=matching)
                self.assertEqual([j["executable"] for j in a["jobs"]], ["draw_toa", "draw_tot"])
                if matching:
                    a["cuts"] = [dict(field="CC1.peak", max=10)]
                waves = {
                    n: Wave(
                        1,
                        1,
                        np.full(20, 100, dtype=np.int16),
                        np.array([999, 1, 1, 1023] + [0] * 16),
                        np.array([999, 10, 10, 1023] + [0] * 16),
                    )
                    for n in names
                }
                waves["CC1"] = Wave(1, 1, np.full(40, 100, dtype=np.int16))
                event = Event(1, 1, waves, source="GCROC")
                path = Path(temp) / write_chunk(Path(temp), 0, [event], 0, config)
                plots = Plots(config, a)
                plots.add(path)
                plots.save()
                f = root().TFile.Open(str(Path(temp) / config["plot_name"]))
                keys = [k for k in f.GetListOfKeys() if k.GetClassName() == "TCanvas"]
                self.assertEqual(len(keys), 2)
                self.assertEqual({k.GetTitle().split(" · ")[-1] for k in keys}, {"TOA", "TOT"})
                for key in keys:
                    metric = key.GetTitle().split(" · ")[-1]
                    canvas = f.Get(key.GetName())
                    for i, name in enumerate(names):
                        hist = canvas.GetPad(i + 1).GetPrimitive(f"h_{name}_{metric}_1")
                        self.assertEqual(hist.GetDimension(), 2)
                        self.assertEqual(hist.GetEntries(), 3)
                        code = 1 if metric == "TOA" else 10
                        for sample in (1, 2):
                            self.assertEqual(hist.GetBinContent(hist.FindBin(sample, code)), 1)
                f.Close()
