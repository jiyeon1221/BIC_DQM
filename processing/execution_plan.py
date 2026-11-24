"""Validate mapping and cut dependencies and prepare processing and plot jobs."""
import math
from pathlib import Path
from processing.channel_selection import build_plan, load_mapping, DQM_ROOT, integer
from processing.event_cuts import calibration, DERIVED, DWC_DIFFERENCE
from processing.aux_cut_config import resolve_mode


def number(value, default, label):
    if value in (None, ""):
        return default
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise ValueError(label + " must be numeric")
    if not math.isfinite(value):
        raise ValueError(label + " must be finite")
    return value


# Find the raw channels needed to evaluate a cut.
def cut_dependencies(field, index):
    if field in DWC_DIFFERENCE:
        dependencies = [d + "_" + s for d in ("DWC1", "DWC2") for s in ("L", "R", "U", "D")]
        if any(n not in index or index[n]["daq"] != "NKFADC" for n in dependencies):
            raise ValueError(
                field + ": position calibration currently requires mapped NKFADC timing channels"
            )
    elif field in DERIVED:
        if field.startswith("DWC"):
            dependencies = [field[:4] + "_" + s for s in ("L", "R", "U", "D")]
            if any(n not in index or index[n]["daq"] != "NKFADC" for n in dependencies):
                raise ValueError(
                    field
                    + ": position calibration currently requires mapped NKFADC timing channels"
                )
        else:
            dependencies = [n for n in index if n.startswith("HODO_" + field[-1] + "_")]
    else:
        try:
            name, metric = field.rsplit(".", 1)
        except ValueError:
            raise ValueError("Unknown cut field: " + field)
        if name not in index or metric not in ("peak", "integral"):
            raise ValueError("Unknown cut field: " + field)
        dependencies = [name]
    if not dependencies:
        raise ValueError("No mapping for cut " + field)
    return dependencies


# Resolve input, matching, and plot settings when a session starts.
def prepare(request, env):
    raw = build_plan(request)
    rows = load_mapping(raw["profile"])
    index = {e["name"]: e for e in rows}
    required = {n for j in raw["jobs"] for n in j["channels"]}
    cuts = []
    if "aux_cut_mode" in request and (request.get("cuts") or request.get("cut_presets")):
        raise ValueError(
            "AUX cut bounds are configured in config/aux_cuts.json, not in the web request"
        )
    requested_cuts = (
        resolve_mode(request["aux_cut_mode"])
        if "aux_cut_mode" in request
        else request.get("cuts", [])
    )
    if not isinstance(requested_cuts, list):
        raise ValueError("Cuts must be a list")
    for cut in requested_cuts:
        if not isinstance(cut, dict):
            raise ValueError("Each cut must have a field and bounds")
        field = str(cut.get("field", ""))
        dependencies = cut_dependencies(field, index)
        required.update(dependencies)
        lo = number(cut.get("min"), None, "Cut minimum")
        hi = number(cut.get("max"), None, "Cut maximum")
        if lo is None and hi is None:
            raise ValueError("Set at least one bound for " + field)
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("Cut minimum exceeds maximum")
        normalized = dict(field=field, min=lo, max=hi)
        exclusive = cut.get("max_exclusive", False)
        if not isinstance(exclusive, bool):
            raise ValueError("max_exclusive must be boolean")
        if exclusive:
            normalized["max_exclusive"] = True
        cuts.append(normalized)
    reasons = []
    if cuts:
        reasons.append("AUX cuts must refer to the same event as the plotted channels")
    if any(job["requires_matching"] for job in raw["jobs"]):
        reasons.append("DWC positions/correlations require coincident channels")
    matching = bool(reasons)
    has_rc = any(index[n]["daq"] == "GCROC" for n in required)
    has_nk = any(index[n]["daq"] != "GCROC" for n in required)
    reference = None
    if matching and has_rc and has_nk:
        reference = "TRIG2"
        if reference not in index or index[reference]["daq"] != "NKFADC":
            raise ValueError("Mixed clock matching requires mapped NKFADC TRIG2")
        required.add(reference)
    # Capture all mapped channels in the required hardware groups.
    groups = {(index[n]["daq"], index[n]["mid"]) for n in required}
    capture = [e["name"] for e in rows if (e["daq"], e["mid"]) in groups]
    calib = calibration(
        Path(env.get("DQM_DWC_CALIBRATION", DQM_ROOT / "config/dwc_calibration.txt"))
    )
    for c in cuts:
        fields = (
            [d + "." + c["field"][-1] for d in ("DWC1", "DWC2")]
            if c["field"] in DWC_DIFFERENCE
            else [c["field"]]
            if c["field"].startswith("DWC") and c["field"] in DERIVED
            else []
        )
        for field in fields:
            key = field.replace(".", "_").upper()
            if key + "_SLOPE" not in calib or key + "_OFFSET" not in calib:
                raise ValueError("Missing calibration: " + key)
    scale = number(request.get("clock_scale"), 0.99998982, "Clock scale")
    tol = number(request.get("tolerance_us"), 1.0, "Tolerance")
    if not 0.9 < scale < 1.1 or not 0 < tol <= 100:
        raise ValueError("Scale must be 0.9..1.1 and tolerance 0..100 us")
    config = dict(
        schema=3,
        matching=matching,
        matching_reasons=reasons,
        decode_batch_size=1000,
        timing=request.get("method") in ("TOA", "TOT", "TOA/TOT"),
        profile=raw["profile"],
        run=raw["run"],
        mapping=rows,
        capture=capture,
        required=sorted(required),
        reference=reference,
        nk_path=env["DQM_DATA_PATH"],
        rc_path=env["RCDAQ_DATA_PATH"],
        reorder=1000,
        queue_limit=4000,
        clock_scale=scale,
        auto_clock=bool(request.get("auto_clock", True)),
        tolerance_us=tol,
        offset_us=number(request.get("offset_us"), None, "Clock offset"),
        calibration=calib,
    )
    method = request.get("method", "IntADC")
    analysis = dict(
        jobs=raw["jobs"],
        method=method,
        type=request.get("type", "layer"),
        count=integer(request.get("count"), -1, "event count", -1),
        first=integer(request.get("first"), 0, "first event"),
        cuts=cuts,
        aux_cut_mode=request.get("aux_cut_mode", "custom" if cuts else "none"),
        revision=1,
    )
    route = "Decode → event matching" if matching else "Decode (independent inputs)"
    if cuts:
        route += " → AUX cuts"
    config["plot_name"] = f"{'matched' if matching else 'decoded'}_{raw['run']}.root"
    raw.update(
        command=f"{'Live' if request.get('live') else 'Batch'} run {raw['run']} → {route} → {method}",
        config=config,
        analysis=analysis,
        route=route,
    )
    raw["notes"] += [
        "Reuse run-level decoded ROOT when input files, mapping and decoder are unchanged; matching reads this cache.",
        (
            "Matching: " + "; ".join(reasons)
            if matching
            else "Independent channel plots: no cross-input matching, even for full/layer/heatmap."
        ),
        (
            "Live updates plots as ROOT chunks arrive and waits until Kill Process."
            if request.get("live")
            else "Batch reads all input, then publishes the final plot once."
        ),
        "Max Event defaults to -1 (all); a positive limit uses up to that many available entries per channel after cuts.",
        "Live batch = 1000 decoded source events in total, before matching/cuts. Output entries can be fewer; incomplete raw records wait for more data.",
    ]
    if config["timing"]:
        raw["notes"].append(
            "TOA/TOT: sample index vs raw code (COLZ); at least 20 samples, sample 0 excluded, only positive values. Histogram entries count filled samples."
        )
    return raw
