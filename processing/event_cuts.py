"""Read DWC calibration and apply AUX cuts to channel metrics."""
import math


def calibration(path):
    result = {}
    if not path.exists():
        return result
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].startswith("DWC"):
            result[parts[0]] = float(parts[1])
    return result


DERIVED = {"DWC1.x": 0, "DWC1.y": 1, "DWC2.x": 2, "DWC2.y": 3, "HODO.L": 4, "HODO.R": 5}
DWC_DIFFERENCE = {"DWC.dx": (0, 2), "DWC.dy": (1, 3)}


def passes(cuts, index, usable, peak, integral, derived):
    for cut in cuts:
        name = cut["field"]
        if name in DWC_DIFFERENCE:
            a, b = DWC_DIFFERENCE[name]
            value = abs(derived[a] - derived[b])
        elif name in DERIVED:
            value = derived[DERIVED[name]]
        else:
            channel, metric = name.rsplit(".", 1)
            i = index[channel]
            value = (peak if metric == "peak" else integral)[i] if usable[i] else math.nan
        if not math.isfinite(value):
            return False
        if cut.get("min") is not None and value < cut["min"]:
            return False
        if cut.get("max") is not None:
            if value >= cut["max"] if cut.get("max_exclusive", False) else value > cut["max"]:
                return False
    return True
