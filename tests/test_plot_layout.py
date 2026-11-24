"""Verify saved ROOT canvases against mapping geometry, including empty cells."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plotting.cpp_plotter import Plots
from storage.root_writer import root
from processing.execution_plan import prepare


def expected_groups(plan, selected):
    groups = {}
    for row in plan["config"]["mapping"]:
        if row["name"] not in selected:
            continue
        label = "SFIL" if row["det"] == 0 else "Bulk"
        if plan["analysis"]["type"] == "layer":
            label += f"_y{row['y']}"
        label += " xm" if row["side"] == 0 else " xp"
        groups.setdefault(label, []).append(row)
    return groups.items()


class PlotLayoutTests(unittest.TestCase):
    def test_full_saved_canvases_follow_mapping_for_both_daqs(self):
        for profile in ("NKDAQ", "RCDAQ"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temp:
                plan = prepare(
                    dict(profile=profile, run=790, type="full", method="IntADC", aux=False),
                    {"DQM_DATA_PATH": "/nk", "RCDAQ_DATA_PATH": "/rc"},
                )
                config = plan["config"]
                config["plot_dir"] = temp
                plots = Plots(config, plan["analysis"])
                plots.save()
                f = root().TFile.Open(str(Path(temp) / config["plot_name"]))
                canvases = [
                    f.Get(k.GetName()) for k in f.GetListOfKeys() if k.GetClassName() == "TCanvas"
                ]
                selected = next(
                    j["channels"]
                    for j in plan["analysis"]["jobs"]
                    if j["executable"] == "draw_intADC"
                )
                seen = set()
                for label, rows in expected_groups(plan, selected):
                    c = next(c for c in canvases if c.GetTitle() == label + " · IntADC")
                    zmin = min(r["z"] for r in rows)
                    zmax = max(r["z"] for r in rows)
                    ymin = min(r["y"] for r in rows)
                    ymax = max(r["y"] for r in rows)
                    nx = zmax - zmin + 1
                    ny = ymax - ymin + 1
                    occupied = set()
                    for row in rows:
                        padno = (ymax - row["y"]) * nx + row["z"] - zmin + 1
                        pad = c.GetPad(padno) if nx * ny > 1 else c
                        hist = pad.GetPrimitive("h_" + row["name"] + "_IntADC_1")
                        self.assertTrue(bool(hist), row["name"])
                        seen.add(row["name"])
                        occupied.add(padno)
                    for padno in set(range(1, nx * ny + 1)) - occupied:
                        self.assertFalse(
                            any(
                                o.InheritsFrom("TH1") for o in c.GetPad(padno).GetListOfPrimitives()
                            )
                        )
                self.assertEqual(seen, set(selected))
                maps = [c for c in canvases if "Heatmap" in c.GetTitle()]
                self.assertEqual(
                    len(maps),
                    len(
                        {(r["det"], r["side"]) for r in config["mapping"] if r["name"] in selected}
                    ),
                )
                f.Close()

    def test_height_layer_saved_canvases_are_one_row_per_side(self):
        for profile in ("NKDAQ", "RCDAQ"):
            for layer, det, y in (("SFIL_y0", 0, 0), ("Bulk_y1", 1, 1)):
                with self.subTest(
                    profile=profile, layer=layer
                ), tempfile.TemporaryDirectory() as temp:
                    plan = prepare(
                        dict(
                            profile=profile,
                            run=790,
                            type="layer",
                            method="IntADC",
                            channels=layer,
                            aux=False,
                        ),
                        {"DQM_DATA_PATH": "/nk", "RCDAQ_DATA_PATH": "/rc"},
                    )
                    config = plan["config"]
                    config["plot_dir"] = temp
                    plots = Plots(config, plan["analysis"])
                    plots.save()
                    f = root().TFile.Open(str(Path(temp) / config["plot_name"]))
                    canvases = [
                        f.Get(k.GetName())
                        for k in f.GetListOfKeys()
                        if k.GetClassName() == "TCanvas"
                    ]
                    self.assertEqual(
                        {c.GetTitle() for c in canvases},
                        {layer + " xm · IntADC", layer + " xp · IntADC"},
                    )
                    selected = plan["analysis"]["jobs"][0]["channels"]
                    for label, rows in expected_groups(plan, selected):
                        self.assertTrue(all(r["det"] == det and r["y"] == y for r in rows))
                        nx = max(r["z"] for r in rows) - min(r["z"] for r in rows) + 1
                        ny = max(r["y"] for r in rows) - min(r["y"] for r in rows) + 1
                        self.assertEqual(ny, 1)
                        c = next(c for c in canvases if c.GetTitle() == label + " · IntADC")
                        zmin = min(r["z"] for r in rows)
                        for row in rows:
                            padno = row["z"] - zmin + 1
                            pad = c.GetPad(padno) if nx > 1 else c
                            self.assertTrue(
                                bool(pad.GetPrimitive("h_" + row["name"] + "_IntADC_1")),
                                row["name"],
                            )
                    f.Close()
