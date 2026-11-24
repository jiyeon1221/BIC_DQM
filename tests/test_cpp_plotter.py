"""Verify native histogram state across live snapshots and rejected inputs."""
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from plotting.cpp_plotter import Plots
from plot_helpers import histogram
from storage.event_data import Event, Wave
from storage.root_writer import write_chunk


class NativePlotterTests(unittest.TestCase):
    def config(self, directory):
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
        return dict(run=1, mapping=[row], calibration={}, matching=False, plot_dir=directory)

    def test_live_snapshots_preserve_raw_samples_and_accumulation(self):
        for method in ("Avg", "Overlay"):
            with self.subTest(method=method), tempfile.TemporaryDirectory() as temp:
                config = self.config(temp)
                name = config["mapping"][0]["name"]
                analysis = dict(
                    type="single",
                    method=method,
                    revision=1,
                    cuts=[],
                    count=-1,
                    first=0,
                    jobs=[dict(executable="draw_" + method.lower(), channels=[name])],
                )
                plots = Plots(config, analysis)
                try:
                    plots.save()
                    for number, (samples, adc) in enumerate(((20, 100), (40, 200))):
                        wave = Wave(number, number, np.full(samples, adc, dtype=np.int16))
                        event = Event(
                            number, number, {name: wave}, source="GCROC", source_event=number
                        )
                        chunk = write_chunk(Path(temp), number, [event], number, config)
                        plots.add(Path(temp) / chunk)
                        plots.save()
                    h = histogram(plots, name, method)
                    self.assertEqual(h.GetEntries(), 58)
                    self.assertEqual(h.GetXaxis().GetLast(), 40)
                    if method == "Avg":
                        self.assertEqual(h.GetBinContent(h.FindBin(1)), 150)
                        self.assertEqual(h.GetBinContent(h.FindBin(39)), 200)
                        self.assertEqual(h.GetBinEntries(h.FindBin(0)), 0)
                    else:
                        self.assertEqual(h.GetBinContent(h.FindBin(1, 100)), 1)
                        self.assertEqual(h.GetBinContent(h.FindBin(1, 200)), 1)
                        self.assertEqual(h.GetBinContent(h.FindBin(0, 100)), 0)
                    self.assertEqual((plots.seen, plots.passed, plots.plotted), (2, 2, 2))
                finally:
                    plots.close()

    def test_mapping_mismatch_does_not_replace_published_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            config = self.config(temp)
            name = config["mapping"][0]["name"]
            analysis = dict(
                type="single",
                method="PeakADC",
                revision=1,
                cuts=[],
                count=-1,
                jobs=[dict(executable="draw_peakADC", channels=[name])],
            )
            plots = Plots(config, analysis)
            try:
                plots.save()
                latest = Path(temp) / "latest.json"
                published = json.loads(latest.read_text())
                other = dict(config, mapping=[dict(config["mapping"][0], ch=140)])
                chunk = write_chunk(Path(temp), 0, [], 0, other)
                with self.assertRaisesRegex(RuntimeError, "mapping mismatch"):
                    plots.add(Path(temp) / chunk)
                self.assertEqual(json.loads(latest.read_text()), published)
                self.assertEqual(plots.seen, 0)
            finally:
                plots.close()
