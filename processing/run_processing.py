#!/usr/bin/env python3
"""Process Live/Batch inputs and save ROOT files, progress, and checkpoints."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collections import Counter
import argparse
import fcntl
import json
import os
import signal
import time
import traceback
from processing.event_pipeline import Pipeline
from matching.cached_pipeline import CachedPipeline
from storage.decoded_cache import inputs_unchanged, input_snapshot
from storage.root_writer import write_chunk
from storage.session_state import atomic_json, checkpoint, load_checkpoint


# Start processing or resume from a checkpoint.
def run(directory, finite=False):
    lock = (directory / ".decode.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    config = json.loads((directory / "config.json").read_text())
    cp = directory / "checkpoint.pkl"
    if cp.exists():
        pipeline = load_checkpoint(cp)
        if pipeline.config != config or not hasattr(pipeline, "batch_decoded"):
            raise RuntimeError("Pipeline configuration/version changed; Execute a new session")
        if pipeline.finished:
            for chunk in pipeline.chunks:
                path = directory / chunk["name"]
                if not path.is_file() or path.stat().st_size != chunk.get(
                    "size", path.stat().st_size
                ):
                    raise RuntimeError("Cached ROOT is missing or incomplete: " + str(path))
            atomic_json(
                directory / "manifest.json",
                dict(
                    schema=2,
                    chunks=pipeline.chunks,
                    events=pipeline.committed,
                    decoded=pipeline.decoded_total,
                    decode_batches=pipeline.decode_batches,
                ),
            )
            atomic_json(directory / "decode_status.json", pipeline.snapshot("complete"))
            return
    elif config.get("seed_dir"):
        seed = Path(config["seed_dir"])
        pipeline = load_checkpoint(seed / "checkpoint.pkl")
        pipeline.config = config
        pipeline.finished = False
        for chunk in pipeline.chunks:
            target = directory / chunk["name"]
            if not target.exists():
                os.link(seed / chunk["name"], target)
    else:
        pipeline = CachedPipeline(config) if config.get("raw_dir") else Pipeline(config)
    pipeline.attach()
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    status = "running"
    last_checkpoint = time.monotonic()
    last_report = 0.0

    def report(phase, force=False):
        nonlocal last_report
        pipeline.phase = phase
        now = time.monotonic()
        if force or now - last_report >= 1.0:
            atomic_json(directory / "decode_status.json", pipeline.snapshot("running"))
            last_report = now

    def manifest():
        return dict(
            schema=2,
            chunks=pipeline.chunks,
            events=pipeline.committed,
            decoded=pipeline.decoded_total,
            decode_batches=pipeline.decode_batches,
        )

    # Commit each decode batch in ROOT, checkpoint, then manifest order.
    def publish(partial=False):
        nonlocal last_checkpoint
        p = pipeline
        if p.batch_decoded < p.batch_size and not partial:
            return
        if not p.batch_decoded and not p.pending:
            return
        p.decode_batches += 1
        count = len(p.pending)
        if count:
            report("writing_root", True)
            state = dict(
                scale=p.matcher.scale, offset_us=p.matcher.offset, sync_pairs=p.matcher.sync_pairs
            )
            name = write_chunk(
                directory, p.sequence, p.pending, p.committed, dict(config, matching_state=state)
            )
            p.committed += count
            p.sequence += 1
            p.chunks.append(
                dict(
                    name=name,
                    sources=dict(Counter(e.source for e in p.pending)),
                    size=(directory / name).stat().st_size,
                    entries=count,
                    total=p.committed,
                    decoded_until=p.decoded_total,
                    decode_batch=p.decode_batches,
                )
            )
            p.pending = []
        print(
            f"Decode batch {p.decode_batches}: {p.batch_decoded} source events; "
            f'published {count} {"decoded" if p.independent else "matched"} records',
            flush=True,
        )
        p.batch_decoded = 0
        # Publish completed ROOT files in the manifest after saving the checkpoint.
        report("checkpointing", True)
        checkpoint(cp, p)
        last_checkpoint = time.monotonic()
        atomic_json(directory / "manifest.json", manifest())

    atomic_json(directory / "manifest.json", manifest())
    try:
        while not stopping:
            changed = pipeline.step(final=finite, report=report)
            publish()
            if finite and pipeline.exhausted():
                if (
                    not pipeline.independent
                    and pipeline.sources
                    and pipeline.rc_rows
                    and not pipeline.matcher.locked
                ):
                    raise RuntimeError(
                        "Insufficient or ambiguous events for NK/RC timestamp synchronization"
                    )
                publish(partial=True)
                pipeline.matcher.dropped_nk += len(pipeline.matcher.nk)
                pipeline.matcher.nk.clear()
                pipeline.matcher.dropped_rc += len(pipeline.matcher.rc)
                pipeline.matcher.rc.clear()
                if not config.get("raw_dir") and not inputs_unchanged(config):
                    raise RuntimeError(
                        "Input changed during Batch decoding; Execute again to use the new input"
                    )
                pipeline.finished = True
                status = "complete"
                break
            waiting_for_raw = (
                config.get("raw_dir") and pipeline.raw_status.get("status") != "complete"
            )
            if finite and not changed and not waiting_for_raw:
                raise RuntimeError(
                    "Finite input cannot advance: missing/incomplete input or unmatched queue limit. "
                    + ", ".join(i["path"] for i in pipeline.snapshot("error")["inputs"])
                )
            atomic_json(
                directory / "decode_status.json",
                pipeline.snapshot("running" if changed else "waiting"),
            )
            if time.monotonic() - last_checkpoint > 10:
                report("checkpointing", True)
                checkpoint(cp, pipeline)
                last_checkpoint = time.monotonic()
            if not changed:
                time.sleep(0.5)
        if stopping and not pipeline.finished:
            publish(partial=True)
            status = "paused"
    except Exception as error:
        status = "error"
        atomic_json(
            directory / "decode_status.json", dict(pipeline.snapshot(status), error=str(error))
        )
        raise
    finally:
        checkpoint(cp, pipeline)
        if status != "error":
            if not config.get("raw_dir"):
                atomic_json(directory / "input_snapshot.json", input_snapshot(config))
            atomic_json(directory / "decode_status.json", pipeline.snapshot(status))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("session", type=Path)
    parser.add_argument("--finite", action="store_true")
    args = parser.parse_args()
    try:
        run(args.session, args.finite)
    except Exception as error:
        try:
            status_path = args.session / "decode_status.json"
            previous = json.loads(status_path.read_text()) if status_path.exists() else {}
            atomic_json(status_path, dict(previous, status="error", error=str(error)))
        except OSError:
            pass
        traceback.print_exc()
        raise SystemExit(1)
