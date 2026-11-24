"""Restore waveforms, triggers, and timestamps from decoded ROOT files."""
import json
import numpy as np
from storage.event_data import Event, Wave
from storage.root_writer import root


def read_events(path, capture, source=None):
    f = root().TFile.Open(str(path))
    if not f or f.IsZombie():
        raise RuntimeError("Cannot read decoded ROOT: " + str(path))
    try:
        rows = json.loads(str(f.Get("mapping_json").GetTitle()))
        tree = f.Get("event_tree")
        if not tree:
            raise RuntimeError("Missing event_tree: " + str(path))
        indices = [(i, r["name"]) for i, r in enumerate(rows) if r["name"] in capture]
        tree.SetBranchStatus("*", False)
        for name in (
            "source",
            "source_event",
            "adc",
            "toa",
            "tot",
            "present",
            "offsets",
            "triggers",
            "timestamps",
            "nk_trigger",
            "nk_time",
            "rc_timestamp",
        ):
            tree.SetBranchStatus(name, True)
        events = []
        for entry in tree:
            entry_source = str(entry.source)
            if source is not None and entry_source != source:
                continue
            adc = np.asarray(entry.adc, dtype=np.int16).copy()
            toa = np.asarray(entry.toa, dtype=np.int16).copy()
            tot = np.asarray(entry.tot, dtype=np.int16).copy()
            waves = {}
            for i, name in indices:
                if not entry.present[i]:
                    continue
                start, end = int(entry.offsets[i]), int(entry.offsets[i + 1])
                waves[name] = Wave(
                    int(entry.triggers[i]),
                    float(entry.timestamps[i]),
                    adc[start:end],
                    toa[start:end],
                    tot[start:end],
                )
            if not waves:
                continue
            rc = int(entry.rc_timestamp)
            event_source = entry_source
            events.append(
                Event(
                    int(entry.source_event) if event_source == "GCROC" else int(entry.nk_trigger),
                    rc / 160.0 if event_source == "GCROC" else float(entry.nk_time),
                    waves,
                    rc_timestamp=rc,
                    source=event_source,
                    source_event=int(entry.source_event),
                )
            )
        return events
    finally:
        f.Close()
