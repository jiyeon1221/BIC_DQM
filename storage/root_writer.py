"""Write event_tree chunks and publish only completed ROOT files."""
from pathlib import Path
import json
import os
import numpy as np
import re


# Serialize channel waveforms into offsets and a flat ADC array.
def raw_arrays(event, names):
    waves = [event.waves.get(n) for n in names]
    sizes = np.array([len(w.adc) if w else 0 for w in waves], dtype=np.int32)
    offsets = np.concatenate((np.zeros(1, dtype=np.int32), np.cumsum(sizes, dtype=np.int32)))
    present = np.array([w is not None for w in waves], dtype=np.uint8)
    pieces = [w.adc for w in waves if w is not None]
    adc = np.concatenate(pieces).astype(np.int16) if pieces else np.zeros(0, dtype=np.int16)
    times = np.array([w.time if w else np.nan for w in waves], dtype=np.float64)
    triggers = np.array([w.trigger if w else 0 for w in waves], dtype=np.ulonglong)
    return adc, offsets, present, times, triggers


ROOT = None


# Load PyROOT and the shared ROOT record definition once.
def root():
    global ROOT
    if ROOT is None:
        import ROOT as module

        ROOT = module
        ROOT.PyConfig.IgnoreCommandLineOptions = True
        ROOT.gROOT.SetBatch(True)
        if not ROOT.gInterpreter.Declare(
            '#include "' + str(Path(__file__).with_name("root_record.h")) + '"'
        ):
            raise RuntimeError("Cannot load ROOT record schema")
    return ROOT


# Write events, mapping, and configuration to a temporary ROOT file, then publish atomically.
def write_chunk(directory, number, events, start, config):
    R = root()
    path = (
        directory / f"{'matched' if config.get('matching',True) else 'decoded'}_{number:06d}.root"
    )
    tmp = path.with_name("." + path.name + ".partial")
    f = R.TFile(str(tmp), "RECREATE")
    if f.IsZombie():
        raise RuntimeError("Cannot create " + str(tmp))
    t = R.TTree(
        "event_tree",
        "Matched events before AUX cuts"
        if config.get("matching", True)
        else "Independent decoded input records",
    )
    record = R.DQMLive.Record()
    record.bind(t)
    rows = config["mapping"]
    names = [e["name"] for e in rows]
    index = {e["name"]: i for i, e in enumerate(rows)}
    daqs = R.std.vector("int")(
        [{"BIC": 0, "JBNU": 1, "NKFADC": 2, "GCROC": 3}[e["daq"]] for e in rows]
    )
    dwc = []
    calib = []
    for d in (1, 2):
        for ax, a, b in [("X", "L", "R"), ("Y", "U", "D")]:
            for side in (a, b):
                i = index.get(f"DWC{d}_{side}", -1)
                dwc.append(i if i >= 0 and rows[i]["daq"] == "NKFADC" else -1)
            calib.extend(
                [
                    config["calibration"].get(f"DWC{d}_{ax}_SLOPE", float("nan")),
                    config["calibration"].get(f"DWC{d}_{ax}_OFFSET", float("nan")),
                ]
            )
    hs = []
    ht = []
    for name in names:
        match = re.fullmatch(r"HODO_([LR])_(\d{2})", name)
        hs.append(("LR".index(match[1])) if match else -1)
        ht.append(int(match[2]) if match else -1)
    record.configure(
        daqs,
        R.std.vector("int")(dwc),
        R.std.vector("double")(calib),
        R.std.vector("int")(hs),
        R.std.vector("int")(ht),
    )
    has_nk = any(e["daq"] != "GCROC" and e["name"] in config.get("capture", names) for e in rows)
    for i, event in enumerate(events):
        adc, offsets, present, timestamps, triggers = raw_arrays(event, names)
        event_has_nk = has_nk and (
            config.get("matching", True) or getattr(event, "source", "") != "GCROC"
        )
        record.event = start + i
        record.nk_trigger = event.key if event_has_nk else 0
        record.rc_timestamp = event.rc_timestamp
        record.nk_time = event.time if event_has_nk else float("nan")
        record.delta_us = event.delta
        record.setRaw(adc, len(adc), offsets, len(present), present, timestamps, triggers)
        record.source.assign(getattr(event, "source", ""))
        record.source_event = getattr(event, "source_event", 0)
        timing = []
        for metric in ("toa", "tot"):
            pieces = []
            for name in names:
                wave = event.waves.get(name)
                if wave is None:
                    continue
                values = getattr(wave, metric, None)
                if values is not None and len(values) != len(wave.adc):
                    raise ValueError("Timing/ADC length mismatch: " + name)
                pieces.append(
                    np.asarray(values, dtype=np.int16)
                    if values is not None
                    else np.full(len(wave.adc), -1, dtype=np.int16)
                )
            timing.append(
                np.ascontiguousarray(np.concatenate(pieces) if pieces else [], dtype=np.int16)
            )
        record.setTiming(timing[0], timing[1], len(adc))
        t.Fill()
    t.Write()
    R.TNamed("mapping_json", json.dumps(config["mapping"])).Write()
    R.TNamed("provenance_json", json.dumps(config)).Write()
    f.Close()
    if not tmp.is_file() or not tmp.stat().st_size:
        raise RuntimeError("Empty ROOT output")
    with tmp.open("rb") as fd:
        os.fsync(fd.fileno())
    os.replace(tmp, path)
    return path.name
