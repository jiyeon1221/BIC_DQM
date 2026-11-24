import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from processing.execution_plan import prepare
from processing.event_cuts import passes
from processing import aux_cut_config as cut_config


class CutConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "cuts.json"
        self.patch = patch.object(cut_config, "CONFIG_PATH", self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.env = {"DQM_DATA_PATH": "/nk", "RCDAQ_DATA_PATH": "/rc"}
        self.request = dict(
            profile="RCDAQ",
            run=1086,
            type="single",
            method="Avg",
            channels="SFIL6_xm_y2",
            aux_cut_mode="dwc_pid",
        )

    def write(self, maximum=5, pid_min=100, pid_field="CC1.peak"):
        self.path.write_text(
            json.dumps(
                {
                    "dwc": [
                        {"field": "DWC.dx", "min": None, "max": maximum},
                        {"field": "DWC1.x", "min": None, "max": None},
                    ],
                    "pid": [{"field": pid_field, "min": pid_min, "max": None}],
                }
            )
        )

    def test_calibration_is_bundled_and_can_be_overridden(self):
        self.write()
        default = prepare(self.request, self.env)["config"]["calibration"]
        self.assertEqual(len(default), 8)
        override = dict(default, DWC1_X_OFFSET=12.5)
        path = Path(self.temp.name) / "dwc.txt"
        path.write_text("".join(f"{key} {value}\n" for key, value in override.items()))
        configured = prepare(self.request, dict(self.env, DQM_DWC_CALIBRATION=str(path)))["config"][
            "calibration"
        ]
        self.assertEqual(configured, override)
        with self.assertRaisesRegex(ValueError, "Missing calibration"):
            prepare(
                self.request, dict(self.env, DQM_DWC_CALIBRATION=str(path.with_suffix(".missing")))
            )

    def test_modes_resolve_server_values_and_keep_snapshot(self):
        self.write()
        first = prepare(self.request, self.env)
        self.assertEqual([c["field"] for c in first["analysis"]["cuts"]], ["DWC.dx", "CC1.peak"])
        self.assertIn("CC1", first["config"]["required"])
        self.assertIn("DWC2_R", first["config"]["required"])
        dwc = prepare(dict(self.request, aux_cut_mode="dwc"), self.env)
        self.assertEqual(len(dwc["analysis"]["cuts"]), 1)
        self.assertNotIn("CC1", dwc["config"]["required"])
        self.write(pid_min=200)
        second = prepare(self.request, self.env)
        self.assertEqual(second["analysis"]["cuts"][1]["min"], 200)
        self.assertEqual(first["analysis"]["cuts"][1]["min"], 100)
        with self.assertRaisesRegex(ValueError, "not in the web request"):
            prepare(dict(self.request, cuts=[dict(field="CC1.peak", min=0)]), self.env)
        self.path.unlink()
        self.assertEqual(
            prepare(dict(self.request, aux_cut_mode="none"), self.env)["analysis"]["cuts"], []
        )

    def test_missing_values_fail_instead_of_silently_disabling_cuts(self):
        self.write(maximum=None)
        with self.assertRaisesRegex(ValueError, "DWC cut is not configured"):
            prepare(self.request, self.env)
        self.write(pid_min=None)
        with self.assertRaisesRegex(ValueError, "PID cut is not configured"):
            prepare(self.request, self.env)
        self.assertEqual(
            len(prepare(dict(self.request, aux_cut_mode="dwc"), self.env)["analysis"]["cuts"]), 1
        )
        for field in ("PS.peak", "MC.integral"):
            self.write(pid_field=field)
            with self.assertRaisesRegex(ValueError, "CC1/CC2 only"):
                prepare(self.request, self.env)
        with self.assertRaisesRegex(ValueError, "AUX cut mode"):
            prepare(dict(self.request, aux_cut_mode="invalid"), self.env)
        self.path.unlink()
        with self.assertRaisesRegex(ValueError, "Cannot read"):
            prepare(self.request, self.env)

    def test_production_dwc_and_cc_peak_thresholds(self):
        self.patch.stop()
        plan = prepare(self.request, self.env)
        cuts = plan["analysis"]["cuts"]
        self.assertEqual([c["field"] for c in cuts], ["DWC.dx", "DWC.dy", "CC1.peak", "CC2.peak"])
        # Verify cut decisions at the configured boundaries.
        bounds = {c["field"]: c["max"] for c in cuts}
        dx, dy = bounds["DWC.dx"], bounds["DWC.dy"]
        cc1, cc2 = bounds["CC1.peak"], bounds["CC2.peak"]
        index = {"CC1": 0, "CC2": 1}
        usable = [1, 1]
        derived = [0, 0, dx, -dy, 0, 0]
        good = [cc1 - 1, cc2 - 1]
        # Large integrals must not affect a PeakADC cut. DWC boundary is inclusive.
        self.assertTrue(passes(cuts, index, usable, good, [1000, 1000], derived))
        for peaks in ([cc1, cc2 - 1], [cc1 - 1, cc2], [cc1 + 1, cc2 + 1]):
            self.assertFalse(passes(cuts, index, usable, peaks, [0, 0], derived))
        self.assertFalse(passes(cuts, index, usable, good, [0, 0], [0, 0, dx + 0.01, 0, 0, 0]))
        self.assertFalse(passes(cuts, index, usable, good, [0, 0], [0, 0, 0, dy + 0.01, 0, 0]))
        self.assertFalse(passes(cuts, index, [0, 1], good, [0, 0], derived))
