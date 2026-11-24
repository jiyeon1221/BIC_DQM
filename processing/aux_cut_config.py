"""Read and validate selected DWC/PID cuts from config/aux_cuts.json."""
import json
import math
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/aux_cuts.json"
CUT_MODES = ("none", "dwc", "dwc_pid")
DWC_FIELDS = {"DWC1.x", "DWC1.y", "DWC2.x", "DWC2.y", "DWC.dx", "DWC.dy"}
PID_FIELDS = {name + "." + metric for name in ("CC1", "CC2") for metric in ("peak", "integral")}


def resolve_mode(mode):
    if mode not in CUT_MODES:
        raise ValueError("AUX cut mode must be none, dwc or dwc_pid")
    if mode == "none":
        return []
    try:
        data = json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError) as error:
        raise ValueError("Cannot read config/aux_cuts.json: " + str(error)) from error
    if not isinstance(data, dict):
        raise ValueError("aux_cuts.json must contain dwc and pid settings")
    result = []
    for group in ("dwc",) if mode == "dwc" else ("dwc", "pid"):
        conditions = data.get(group)
        if not isinstance(conditions, list):
            raise ValueError("aux_cuts.json: " + group + " must be a list")
        configured = []
        for cut in conditions:
            allowed = DWC_FIELDS if group == "dwc" else PID_FIELDS
            if not isinstance(cut, dict) or cut.get("field") not in allowed:
                raise ValueError(
                    group + ": only DWC positions/differences are allowed"
                    if group == "dwc"
                    else "PID uses CC1/CC2 only"
                )
            lo, hi = cut.get("min"), cut.get("max")
            for value in (lo, hi):
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValueError(group + ": bounds must be finite numbers or null")
            if lo is not None and hi is not None and lo > hi:
                raise ValueError(group + ": minimum exceeds maximum")
            exclusive = cut.get("max_exclusive", False)
            if not isinstance(exclusive, bool):
                raise ValueError(group + ": max_exclusive must be boolean")
            if lo is not None or hi is not None:
                normalized = dict(field=cut["field"], min=lo, max=hi)
                if exclusive:
                    normalized["max_exclusive"] = True
                configured.append(normalized)
        if not configured:
            raise ValueError(
                group.upper() + " cut is not configured: set bounds in config/aux_cuts.json"
            )
        result.extend(configured)
    return result
