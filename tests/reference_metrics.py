"""Python reference implementation for C++ ADC and position calculations."""
import re
import math


def pulse(adc, daq):
    import numpy as np

    a = np.asarray(adc, dtype=np.float64)
    if daq == "GCROC":
        if len(a) < 20 or len(a) > 40:
            return (False, math.nan, math.nan, math.nan)
        baseline = float(a[1:5].mean())
        signal = a[1:] - baseline
    elif daq == "NKFADC":
        if not len(a):
            return (False, math.nan, math.nan, math.nan)
        baseline = float(a[:30].mean())
        signal = baseline - a
    else:
        baseline = 0.0
        signal = a[10:60] if daq == "BIC" else a[:240]
        if not len(signal) or (daq == "BIC" and not np.any(a)):
            return (False, 0.0, math.nan, math.nan)
    peak = float(signal.max())
    if daq == "NKFADC":
        peak = max(0.0, peak)
    return True, baseline, peak, float(signal.sum())


def arrival(adc):
    import numpy as np

    a = np.asarray(adc, dtype=float)
    if len(a) < 31:
        return math.nan
    signal = a[:30].mean() - a
    maximum = signal.max()
    if maximum <= 0:
        return math.nan
    threshold = 0.3 * maximum
    crossings = np.flatnonzero(signal[1:] > threshold)
    if len(crossings):
        s = int(crossings[0]) + 1
        y0, y1 = signal[s - 1 : s + 1]
        return 2 * (s - 1) + 2 * (threshold - y0) / (y1 - y0) if y1 != y0 else 2 * s
    return math.nan


def arrays(event, rows, calib):
    import numpy as np

    count = len(rows)
    present = np.zeros(count, dtype=np.uint8)
    usable = present.copy()
    offsets = np.zeros(count + 1, dtype=np.int32)
    baseline = np.full(count, np.nan)
    peak = baseline.copy()
    integral = baseline.copy()
    timestamps = baseline.copy()
    triggers = np.zeros(count, dtype=np.ulonglong)
    pieces = []
    times = {}
    index = {e["name"]: i for i, e in enumerate(rows)}
    for i, row in enumerate(rows):
        name = row["name"]
        wave = event.waves.get(name)
        offsets[i + 1] = offsets[i]
        if wave is None:
            continue
        present[i] = 1
        pieces.append(wave.adc)
        offsets[i + 1] += len(wave.adc)
        usable[i], baseline[i], peak[i], integral[i] = pulse(wave.adc, row["daq"])
        timestamps[i] = wave.time
        triggers[i] = wave.trigger
        if name.startswith("DWC") and row["daq"] == "NKFADC":
            times[name] = arrival(wave.adc)
    derived = np.full(6, np.nan)
    for d in (1, 2):
        for ax, a, b in [("X", "L", "R"), ("Y", "U", "D")]:
            key = f"DWC{d}_{ax}"
            if key + "_SLOPE" not in calib or key + "_OFFSET" not in calib:
                continue
            delta = times.get(f"DWC{d}_{a}", math.nan) - times.get(f"DWC{d}_{b}", math.nan)
            derived[2 * (d - 1) + (ax == "Y")] = (
                calib[key + "_SLOPE"] * delta + calib[key + "_OFFSET"]
            )
    for side in ("L", "R"):
        candidates = [
            (integral[i], int(e["name"][-2:]))
            for i, e in enumerate(rows)
            if re.fullmatch(f"HODO_{side}_\\d{{2}}", e["name"]) and usable[i]
        ]
        if candidates:
            derived[4 + (side == "R")] = max(candidates)[1]
    adc = np.concatenate(pieces).astype(np.int16) if pieces else np.zeros(0, dtype=np.int16)
    return adc, offsets, present, usable, baseline, peak, integral, timestamps, triggers, derived
