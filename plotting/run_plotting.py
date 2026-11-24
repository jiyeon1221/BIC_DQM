#!/usr/bin/env python3
"""Update Live plots per ROOT chunk; draw Batch plots once decoding finishes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
import fcntl
import json
import time
import traceback
from storage.session_state import atomic_json
from storage.decoded_cache import decode_status
from plotting.cpp_plotter import Plots


def read(path, default=None):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default if default is not None else {}


def run(directory):
    with (directory / ".analysis.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = read(directory / "config.json")
        live = config.get("live", True)
        data_dir = Path(config.get("data_dir", directory))
        revision = None
        processed = 0
        plots = None
        published = False

        def report(phase, total, current=None):
            atomic_json(
                directory / "analysis_status.json",
                dict(
                    status="running",
                    phase=phase,
                    revision=revision,
                    chunks=processed,
                    total_chunks=total,
                    current_chunk=current,
                    seen=plots.seen,
                    evaluated=plots.evaluated,
                    passed=plots.passed,
                    plotted=plots.plotted,
                    updated=time.time(),
                ),
            )

        while True:
            analysis = read(directory / "analysis.json")
            if not live:
                decode = decode_status(data_dir)
                if decode.get("status") != "complete":
                    state = (
                        "error"
                        if decode.get("status") == "error"
                        else "stopped"
                        if decode.get("status") == "paused"
                        else "waiting_for_decode"
                    )
                    status = dict(
                        status=state,
                        revision=analysis["revision"],
                        chunks=0,
                        seen=0,
                        passed=0,
                        updated=time.time(),
                    )
                    if state == "error":
                        status["error"] = "Final plot not generated: " + decode.get(
                            "error", "decoding failed"
                        )
                    atomic_json(directory / "analysis_status.json", status)
                    if state in ("error", "stopped"):
                        return
                    time.sleep(1)
                    continue
            manifest = read(data_dir / "manifest.json", {"chunks": []})
            if analysis["revision"] != revision:
                if plots is not None and hasattr(plots, "close"):
                    plots.close()
                revision = analysis["revision"]
                processed = 0
                plots = Plots(config, analysis)
                published = False
                atomic_json(
                    directory / "analysis_status.json",
                    dict(status="replaying", revision=revision, chunks=0, seen=0, passed=0),
                )
            for chunk in manifest["chunks"][processed:]:
                if read(directory / "analysis.json")["revision"] != revision:
                    break
                report("reading_root", len(manifest["chunks"]), processed + 1)
                plots.add(data_dir / chunk["name"])
                processed += 1
                if live:
                    report("saving_plots", len(manifest["chunks"]))
                    plots.save()
                atomic_json(
                    directory / "analysis_status.json",
                    dict(
                        status="running",
                        revision=revision,
                        chunks=processed,
                        seen=plots.seen,
                        evaluated=plots.evaluated,
                        passed=plots.passed,
                        plotted=plots.plotted,
                        updated=time.time(),
                    ),
                )
            if read(directory / "analysis.json")["revision"] != revision:
                continue
            if not live:
                if not published:
                    report("saving_plots", len(manifest["chunks"]))
                    plots.save()
                    published = True
                atomic_json(
                    directory / "analysis_status.json",
                    dict(
                        status="complete",
                        revision=revision,
                        chunks=processed,
                        seen=plots.seen,
                        evaluated=plots.evaluated,
                        passed=plots.passed,
                        plotted=plots.plotted,
                        updated=time.time(),
                    ),
                )
                return
            else:
                decode = decode_status(data_dir)
                if decode.get("status") in ("paused", "complete", "error") and processed == len(
                    read(data_dir / "manifest.json", {"chunks": []})["chunks"]
                ):
                    atomic_json(
                        directory / "analysis_status.json",
                        dict(
                            status="caught_up",
                            revision=revision,
                            chunks=processed,
                            seen=plots.seen,
                            evaluated=plots.evaluated,
                            passed=plots.passed,
                            plotted=plots.plotted,
                            updated=time.time(),
                        ),
                    )
                    return
            # Wait for new ROOT chunks during Live processing.
            time.sleep(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("session", type=Path)
    a = ap.parse_args()
    try:
        run(a.session)
    except Exception as e:
        atomic_json(a.session / "analysis_status.json", dict(status="error", error=str(e)))
        traceback.print_exc()
        raise SystemExit(1)
