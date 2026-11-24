"""Run with: python3 -m unittest discover -s web/tests -v"""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from processing.channel_selection import build_plan, load_mapping, MAPPING_FILES, native_dwc


class RoutingTests(unittest.TestCase):
    def request(self, **changes):
        return dict(
            dict(
                profile="RCDAQ",
                run=1086,
                type="module",
                method="Avg",
                channels="SFIL6",
                count=100,
                aux=True,
            ),
            **changes
        )

    def test_height_layers_use_geometry_across_modules(self):
        for profile in ("NKDAQ", "RCDAQ"):
            rows = load_mapping(profile)
            for layer, det, y in (("SFIL_y0", 0, 0), ("Bulk_y1", 1, 1)):
                with self.subTest(profile=profile, layer=layer):
                    jobs = build_plan(
                        self.request(
                            profile=profile,
                            type="layer",
                            method="IntADC",
                            channels=layer.lower(),
                            aux=False,
                        )
                    )["jobs"]
                    selected = {n for job in jobs for n in job["channels"]}
                    expected = {e["name"] for e in rows if e["det"] == det and e["y"] == y}
                    self.assertEqual(selected, expected)
                    self.assertGreater(len({e["z"] for e in rows if e["name"] in selected}), 1)
                    self.assertEqual({e["side"] for e in rows if e["name"] in selected}, {0, 1})
                    self.assertFalse(any(j["requires_matching"] for j in jobs))

    def test_layer_membership_uses_mapping_not_channel_spelling(self):
        rows = copy.deepcopy(load_mapping("NKDAQ"))
        moved = next(e for e in rows if e["name"] == "SFIL4_xm_y0")
        moved["y"] = 9
        jobs = build_plan(
            self.request(
                profile="NKDAQ", type="layer", method="PeakADC", channels="SFIL_y9", aux=False
            ),
            rows,
        )["jobs"]
        self.assertEqual(jobs[0]["channels"], ["SFIL4_xm_y0"])

    def test_invalid_layer_selection_and_methods_rejected(self):
        for selector in ("SFIL4", "SFIL_y99", "SFIL_y0 Bulk_y0", ""):
            with self.subTest(selector=selector), self.assertRaises(ValueError):
                build_plan(
                    self.request(type="layer", method="IntADC", channels=selector, aux=False)
                )
        for method in ("Avg", "Overlay", "Waveform"):
            with self.subTest(method=method), self.assertRaisesRegex(ValueError, "Layer requires"):
                build_plan(self.request(type="layer", method=method, channels="SFIL_y0", aux=False))

    def test_current_rc_module_and_aux(self):
        jobs = build_plan(self.request())["jobs"]
        self.assertEqual(
            [(j["reader"], j["executable"], j["daqs"]) for j in jobs],
            [("RCDAQ", "draw_avg", ["GCROC"]), ("NKDAQ", "draw_AUX", ["NKFADC"])],
        )
        self.assertEqual(jobs[0]["args"], ["1086", "100", "SFIL6_*"])
        self.assertTrue(all(j["profile"] == "RCDAQ" for j in jobs))

    def test_nk_supports_all_three_daqs(self):
        jobs = build_plan(
            self.request(
                profile="NKDAQ", type="single", channels="SFIL6_xm_y2 HODO_L_01 CC1", aux=False
            )
        )["jobs"]
        self.assertEqual(jobs[0]["daqs"], ["BIC", "JBNU", "NKFADC"])
        self.assertEqual(jobs[0]["reader"], "NKDAQ")

    def test_rc_mapping_is_independent(self):
        with patch.dict(MAPPING_FILES, {"NKDAQ": Path("/does-not-exist/nkdaq_mapping.h")}):
            self.assertEqual(len(build_plan(self.request())["jobs"]), 2)

    def test_future_gcroc_aux_does_not_use_nk(self):
        rows = copy.deepcopy(load_mapping("RCDAQ"))
        available = iter(
            ch for ch in range(144) if ch not in {e["ch"] for e in rows if e["daq"] == "GCROC"}
        )
        for row in rows:
            if row["name"].startswith(("DWC", "CC")):
                row.update(daq="GCROC", mid=-1, ch=next(available))
        jobs = build_plan(self.request(), rows)["jobs"]
        self.assertTrue(all(j["reader"] == "RCDAQ" for j in jobs))
        self.assertFalse(any(j["executable"] in ("DWC", "draw_AUX") for j in jobs))
        self.assertEqual(
            {n for j in jobs[1:] for n in j["channels"]},
            {e["name"] for e in rows if e["name"].startswith(("DWC", "CC"))},
        )

    def test_future_gcroc_hodoscope(self):
        rows = copy.deepcopy(load_mapping("RCDAQ"))
        available = iter(
            ch for ch in range(144) if ch not in {e["ch"] for e in rows if e["daq"] == "GCROC"}
        )
        for row in rows:
            if row["name"].startswith("HODO_"):
                row.update(daq="GCROC", mid=-1, ch=next(available))
        jobs = build_plan(self.request(type="hodoscope", aux=False), rows)["jobs"]
        self.assertEqual(jobs[0]["reader"], "RCDAQ")
        self.assertEqual(jobs[0]["args"][2:], ["HODO_*"])
        self.assertEqual(len(jobs[0]["channels"]), 32)

    def test_partially_moved_aux_splits_readers(self):
        rows = copy.deepcopy(load_mapping("RCDAQ"))
        next(e for e in rows if e["name"] == "CC1").update(daq="GCROC", mid=-1, ch=0)
        jobs = build_plan(self.request(), rows)["jobs"]
        cc_jobs = {n: j["reader"] for j in jobs for n in j["channels"] if n.startswith("CC")}
        self.assertEqual(cc_jobs, {"CC1": "RCDAQ", "CC2": "NKDAQ"})
        self.assertIn("DWC", [j["executable"] for j in jobs])

    def test_mixed_selection(self):
        jobs = build_plan(self.request(type="single", channels="CC1 SFIL6_xm_y2", aux=False))[
            "jobs"
        ]
        self.assertEqual([j["reader"] for j in jobs], ["NKDAQ", "RCDAQ"])

    def test_wrong_profile_channel_rejected(self):
        with self.assertRaisesRegex(ValueError, "Not in selected mapping"):
            build_plan(self.request(type="single", channels="SFIL8_xm_y2", aux=False))

    def test_full_selection_has_short_filenames(self):
        for profile in ("NKDAQ", "RCDAQ"):
            jobs = build_plan(self.request(profile=profile, type="full", aux=False))["jobs"]
            self.assertLess(len("_".join(jobs[-1]["args"][2:])), 180)

    def test_waveform_count_and_skip(self):
        jobs = build_plan(self.request(method="Waveform", count=10, first=20, aux=False))["jobs"]
        self.assertEqual(jobs[0]["args"][:3], ["1086", "20", "10"])
        self.assertTrue(build_plan(self.request(method="Waveform", count=101))["jobs"])
        self.assertEqual(
            build_plan(self.request(method="Waveform", count="", aux=False))["jobs"][0]["args"][2],
            "-1",
        )

    def test_dwc_reconstruction_requires_complete_nkfadc(self):
        rows = copy.deepcopy(load_mapping("RCDAQ"))
        self.assertTrue(native_dwc(rows))
        next(e for e in rows if e["name"] == "DWC1_R")["mid"] = 9
        self.assertFalse(native_dwc(rows))


if __name__ == "__main__":
    unittest.main()
