"""Expand user selections into channel jobs using mapping DAQ and position fields."""
from pathlib import Path
import re
import shlex

DQM_ROOT = Path(__file__).resolve().parent.parent
MAPPING_FILES = {
    name: DQM_ROOT / "mapping" / f"{name.lower()}_mapping.h" for name in ("NKDAQ", "RCDAQ")
}
READERS = {"BIC": "NKDAQ", "JBNU": "NKDAQ", "NKFADC": "NKDAQ", "GCROC": "RCDAQ"}
METHODS = {
    "IntADC": "draw_intADC",
    "PeakADC": "draw_peakADC",
    "Avg": "draw_avg",
    "Overlay": "draw_overlay",
    "Waveform": "draw_waveform",
    "TOA": "draw_toa",
    "TOT": "draw_tot",
    "TOA/TOT": "draw_toa_tot",
}
ROW = re.compile(
    r'\{\s*"(\w+)"\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*"([^"]+)"\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\}'
)


def layer_name(entry):
    detector = {0: "SFIL", 1: "Bulk"}.get(entry["det"])
    return f"{detector}_y{entry['y']}" if detector and entry["y"] >= 0 else None


def load_mapping(profile):
    if profile not in MAPPING_FILES:
        raise ValueError("Select NKDAQ or RCDAQ")
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", MAPPING_FILES[profile].read_text(), flags=re.S)
    entries, names, hardware = [], set(), set()
    for values in ROW.findall(text):
        daq, mid, ch, name, det, side, sma, z, y = values
        entry = dict(
            daq=daq,
            mid=int(mid),
            ch=int(ch),
            name=name,
            det=int(det),
            side=int(side),
            sma=int(sma),
            z=int(z),
            y=int(y),
        )
        if daq not in READERS:
            raise ValueError(f"{name}: unsupported DAQ {daq}")
        key = (daq, -1 if daq == "GCROC" else entry["mid"], entry["ch"])
        if name in names or key in hardware:
            raise ValueError(f"Duplicate mapping: {name} / {key}")
        maximum = 144 if daq == "GCROC" else 4 if daq == "NKFADC" else 32
        minimum = 0 if daq == "GCROC" else 1
        if not minimum <= entry["ch"] < maximum + (minimum == 1):
            raise ValueError(f"{name}: invalid channel")
        if daq != "GCROC" and entry["mid"] < 0:
            raise ValueError(f"{name}: missing MID")
        if entry["det"] >= 0 and (
            entry["det"] not in (0, 1)
            or entry["side"] not in (0, 1)
            or entry["z"] < 0
            or entry["y"] < 0
        ):
            raise ValueError(f"{name}: invalid calorimeter geometry")
        entry["reader"] = READERS[daq]
        entry["module"] = name.split("_")[0] if entry["det"] >= 0 else None
        entry["layer"] = layer_name(entry)
        entries.append(entry)
        names.add(name)
        hardware.add(key)
    if not entries:
        raise ValueError(f"{profile}: empty mapping")
    return entries


def integer(value, default, label, minimum=0, maximum=None):
    if value is None or value == "":
        value = default
    if isinstance(value, bool) or not re.fullmatch(r"-?\d+", str(value)):
        raise ValueError(f"{label} must be an integer")
    result = int(value)
    if result < minimum or maximum is not None and result > maximum:
        raise ValueError(f"Invalid {label}")
    return result


def native_dwc(rows):
    by_name = {e["name"]: e for e in rows}
    for detector in (1, 2):
        group = [by_name.get(f"DWC{detector}_{side}") for side in ("R", "L", "U", "D")]
        if any(e is None or e["daq"] != "NKFADC" for e in group):
            return False
        if len({e["mid"] for e in group}) != 1 or len({e["ch"] for e in group}) != 4:
            return False
    return True


def build_plan(request, entries=None):
    profile = request.get("profile", "NKDAQ")
    rows = load_mapping(profile) if entries is None else entries

    rows = [dict(e, reader=READERS[e["daq"]], layer=layer_name(e)) for e in rows]
    by_name = {e["name"]: e for e in rows}
    run = integer(request.get("run"), None, "run", 1, 99999)
    kind = request.get("type", "layer")
    method = request.get("method", "IntADC")
    if (
        kind not in ("single", "layer", "module", "heatmap", "full", "hodoscope", "DWC")
        or method not in METHODS
    ):
        raise ValueError("Unknown plot type or method")
    if kind == "layer" and method not in ("IntADC", "PeakADC"):
        raise ValueError("Layer requires IntADC or PeakADC")
    if kind == "heatmap" and method not in ("IntADC", "PeakADC"):
        raise ValueError("Heatmap requires IntADC or PeakADC")
    if kind in ("full", "hodoscope") and method == "Waveform":
        raise ValueError("Choose single for waveform display")
    timing = method in ("TOA", "TOT", "TOA/TOT")
    if timing and (profile != "RCDAQ" or kind != "single"):
        raise ValueError("TOA/TOT require RCDAQ single mode")
    count = integer(request.get("count"), -1, "event count", -1)
    if count == 0:
        raise ValueError("Event count must be positive or -1 (all)")
    first = integer(request.get("first"), 0, "first event")
    tokens = str(request.get("channels", "")).split()
    jobs, notes = [], []

    def add(reader, executable, args, selected):
        job = dict(
            reader=reader,
            executable=executable,
            args=[str(a) for a in args],
            channels=[e["name"] for e in selected],
            daqs=sorted({e["daq"] for e in selected}),
            profile=profile,
            run=run,
        )
        job["command"] = shlex.join([f"../analysis/{reader}/{executable}"] + job["args"])
        # DWC positions and correlations require channels from the same event.
        job["requires_matching"] = executable in ("draw_AUX", "DWC")
        jobs.append(job)

    def generic(selected, selected_method=None):
        actual = selected_method or method
        if actual == "TOA/TOT":
            generic(selected, "TOA")
            generic(selected, "TOT")
            return
        for reader in ("NKDAQ", "RCDAQ"):
            group = [e for e in selected if e["reader"] == reader]
            if not group:
                continue
            executable = METHODS[actual]
            if actual == "Waveform" and reader == "NKDAQ":
                executable = "draw_singleWaveform"
            args = [run, first, count] if actual == "Waveform" else [run, count]
            selectors = [e["name"] for e in group]

            if all(e["det"] >= 0 for e in group):
                modules = list(dict.fromkeys(e["name"].split("_")[0] for e in group))
                expanded = {
                    e["name"]
                    for e in rows
                    if e["reader"] == reader and e["name"].split("_")[0] in modules
                }
                if expanded == {e["name"] for e in group}:
                    selectors = [m + "_*" for m in modules] if reader == "RCDAQ" else modules
            if reader == "RCDAQ" and all(e["name"].startswith("HODO_") for e in group):
                hodo = {
                    e["name"]
                    for e in rows
                    if e["reader"] == reader and e["name"].startswith("HODO_")
                }
                if hodo == {e["name"] for e in group}:
                    selectors = ["HODO_*"]
            add(reader, executable, args + selectors, group)

    calo = [e for e in rows if e["det"] >= 0]
    if kind == "single":
        if not tokens:
            raise ValueError("Enter channel names")
        unknown = [name for name in tokens if name not in by_name]
        if unknown:
            raise ValueError("Not in selected mapping: " + ", ".join(unknown))
        if timing and any(by_name[name]["daq"] != "GCROC" for name in tokens):
            raise ValueError("TOA/TOT require GCROC channels in the mapping")
        generic([by_name[name] for name in dict.fromkeys(tokens)])
    elif kind == "layer":
        if len(tokens) != 1:
            raise ValueError("Select one height layer, e.g. SFIL_y0 or Bulk_y0")
        selected = [e for e in calo if e["layer"].casefold() == tokens[0].casefold()]
        if not selected:
            raise ValueError("Height layer not in selected mapping: " + tokens[0])
        selected.sort(key=lambda e: (e["side"], e["z"], e["name"]))
        generic(selected)
    elif kind == "module":
        selected = [e for e in calo if e["name"].split("_")[0] in tokens]
        if len(tokens) != 1 or not selected:
            raise ValueError("Select one module from the mapping")
        generic(selected)
    elif kind in ("heatmap", "full"):
        for reader in ("NKDAQ", "RCDAQ"):
            group = [e for e in calo if e["reader"] == reader]
            if group:
                add(
                    reader,
                    "draw_heatmap",
                    [run, count, "peak" if method == "PeakADC" else "int"],
                    group,
                )
        if kind == "full":
            generic(calo)
    elif kind == "hodoscope":
        group = [e for e in rows if e["name"].startswith("HODO_")]
        if not group:
            raise ValueError("No hodoscope channels in this mapping")
        if all(e["reader"] == "NKDAQ" for e in group):
            add(
                "NKDAQ",
                "hodoscope",
                [run, count, {"IntADC": "i", "PeakADC": "p", "Avg": "a", "Overlay": "o"}[method]],
                group,
            )
        else:
            generic(group)
    elif kind == "DWC":
        group = [e for e in rows if e["name"].startswith("DWC")]
        if not group:
            raise ValueError("No DWC channels in this mapping")
        if native_dwc(rows):
            add("NKDAQ", "DWC", [run, count], group)
        else:
            generic(group, "Avg")
            notes.append(
                "DWC: average channel waveforms. Position reconstruction requires the NKFADC timing reader."
            )
    if request.get("aux"):
        aux = [e for e in rows if e["name"].startswith("DWC") or re.fullmatch(r"CC\d+", e["name"])]
        if not aux:
            raise ValueError("No AUX channels in the selected mapping")
        cc = [e for e in aux if e["name"].startswith("CC")]
        if (
            native_dwc(rows)
            and len(cc) == 2
            and {e["name"] for e in cc} == {"CC1", "CC2"}
            and all(e["reader"] == "NKDAQ" for e in cc)
        ):
            add("NKDAQ", "draw_AUX", [run, count], aux)
        else:
            dwc = [e for e in aux if e["name"].startswith("DWC")]
            if native_dwc(rows):
                add("NKDAQ", "DWC", [run, count], dwc)
            elif dwc:
                generic(dwc, "Avg")
                notes.append(
                    "DWC: average channel waveforms; no unsupported timing/position conversion is applied."
                )
            generic(cc, "PeakADC")
    if not jobs:
        raise ValueError("Nothing to draw in the selected mapping")
    return dict(
        profile=profile,
        run=run,
        jobs=jobs,
        command=" ; ".join(j["command"] for j in jobs),
        notes=notes,
        request=request,
    )
