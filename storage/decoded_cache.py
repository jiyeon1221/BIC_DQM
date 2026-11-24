"""Identify shared run caches by input files and decoder version."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


def input_path(config, row):
    if row["daq"] == "GCROC":
        return Path(config["rc_path"]) / f"2608CERN_ROC_0-{config['run']:08d}-0000.evt"
    token = "FADC" if row["daq"] == "NKFADC" else row["daq"]
    return Path(config["nk_path"]) / f"Run_{config['run']:05d}_{token}_{row['mid']}.dat"


def file_identity(path, live=False):
    path = path.resolve()
    identity = dict(path=str(path))
    try:
        stat = path.stat()
        identity.update(device=stat.st_dev, inode=stat.st_ino)
        if not live:
            identity.update(size=stat.st_size, mtime_ns=stat.st_mtime_ns, ctime_ns=stat.st_ctime_ns)
    except FileNotFoundError:
        identity["missing"] = True
    return identity


def decoder_version():
    paths = [
        "decoding/nkdaq_reader.py",
        "decoding/rcdaq_decoder.py",
        "decoding/rcdaq_buffer_reader.h",
        "processing/event_pipeline.py",
        "processing/run_processing.py",
        "processing/waveform_metrics.h",
        "storage/root_writer.py",
        "storage/root_record.h",
        "storage/event_data.py",
    ]
    files = [ROOT / name for name in paths if (ROOT / name).is_file()]
    files += sorted((ROOT / "decoding").glob("*.C"))
    versions = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    library = ROOT / "decoding/rcdaq/install/lib/libNoRootEvent.so"
    if library.exists():
        versions["rcdaq_library"] = file_identity(library)
    return digest(versions)


def raw_config(config, live):
    # Cache mapped inputs together for reuse across channel and method selections.
    rows = config.get("mapping", [])
    required = set(config.get("capture", []))
    capture = [
        r["name"] for r in rows if live or r["name"] in required or input_path(config, r).exists()
    ]
    result = {
        k: v
        for k, v in config.items()
        if k
        not in (
            "plot_name",
            "plot_dir",
            "matching_reasons",
            "required",
            "reference",
            "clock_scale",
            "tolerance_us",
            "offset_us",
            "auto_clock",
        )
    }
    result.update(
        matching=False,
        required=[],
        reference=None,
        capture=capture,
        timing=any(r["daq"] == "GCROC" and r["name"] in capture for r in rows),
        clock_scale=1.0,
        tolerance_us=1.0,
        offset_us=None,
        auto_clock=False,
        live=live,
        cache_schema=1,
        decoder_version=decoder_version(),
    )
    paths = sorted({input_path(config, r).resolve() for r in rows if r["name"] in capture})
    result["input_identity"] = [file_identity(p, live) for p in paths]
    return result


def inputs_unchanged(config):
    return config.get("input_identity", []) == [
        file_identity(Path(i["path"]), config.get("live", False))
        for i in config.get("input_identity", [])
    ]


def complete_cache(directory):
    try:
        status = json.loads((directory / "decode_status.json").read_text())
        manifest = json.loads((directory / "manifest.json").read_text())
        return status.get("status") == "complete" and all(
            (directory / c["name"]).is_file()
            and (directory / c["name"]).stat().st_size == c["size"]
            for c in manifest["chunks"]
        )
    except (OSError, ValueError, KeyError):
        return False


def input_snapshot(config):
    return [file_identity(Path(i["path"])) for i in config.get("input_identity", [])]


def seed_cache(run_dir, config):
    # Resume saved reader positions across Live/Batch changes when inputs are unchanged.
    def signature(value):
        return digest(
            {k: v for k, v in value.items() if k not in ("live", "input_identity", "seed_dir")}
        )

    for directory in sorted(run_dir.glob("*/raw")):
        try:
            previous = json.loads((directory / "config.json").read_text())
            state = json.loads((directory / "decode_status.json").read_text())
            snapshot = json.loads((directory / "input_snapshot.json").read_text())
            manifest = json.loads((directory / "manifest.json").read_text())
            if (
                state.get("status") in ("complete", "paused")
                and signature(previous) == signature(config)
                and snapshot == input_snapshot(config)
                and (directory / "checkpoint.pkl").is_file()
                and all(
                    (directory / c["name"]).stat().st_size == c["size"] for c in manifest["chunks"]
                )
            ):
                return directory
        except (OSError, ValueError, KeyError):
            continue
    return None


def decode_status(directory):
    # Detect dead shared producers so consumers do not wait indefinitely.
    path = directory / "decode_status.json"
    try:
        state = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    metadata = directory / "decode_process.json"
    if state.get("status") not in ("starting", "running", "waiting") or not metadata.exists():
        return state
    try:
        pid = json.loads(metadata.read_text())["pid"]
        args = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
        if str(directory).encode() in args and any(
            a.endswith(b"/processing/run_processing.py") for a in args
        ):
            return state
    except (OSError, ValueError, KeyError):
        pass
    latest = json.loads(path.read_text())
    if latest.get("status") not in ("starting", "running", "waiting"):
        return latest
    return dict(
        latest,
        status="error",
        error="Shared data worker exited unexpectedly: " + str(directory / "decode.log"),
    )
