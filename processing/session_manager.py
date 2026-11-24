"""Manage sessions, worker lifecycles, and status queries."""
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
from processing.execution_plan import prepare
from processing.input_progress import input_progress
from storage.session_state import atomic_json as write
from storage.decoded_cache import raw_config, digest, complete_cache, seed_cache, decode_status


def read(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default if default is not None else {}


class Controller:
    def __init__(self, env, output):
        self.env = env
        self.output = Path(output).resolve()
        self.base = self.output / ".sessions"
        self.decoded = self.output.parent / "decoded"
        self.legacy_base = ROOT / "output/sessions"
        self.base.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.children = []

    def plan(self, request):
        if request.get("cuts") or request.get("cut_presets"):
            raise ValueError("Select an AUX cut mode; edit bounds in config/aux_cuts.json")
        return prepare(request, self.env)

    def directory(self, session):
        if not re.fullmatch(r"[0-9a-f]{16}", str(session)):
            raise ValueError("Invalid session")
        path = self.base / session
        if not (path / "config.json").is_file():
            path = self.legacy_base / session
        if not (path / "config.json").is_file():
            raise ValueError("Session not found")
        return path

    def process(self, pid):
        """Identify DQM processes by owner, executable path, and session path."""
        proc = Path("/proc") / str(pid)
        try:
            if proc.stat().st_uid != os.getuid():
                return None
            args = [os.fsdecode(a) for a in (proc / "cmdline").read_bytes().split(b"\0") if a]
            if not args or not re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", Path(args[0]).name):
                return None
            i = 1
            while i < len(args) and args[i] in (
                "-u",
                "-B",
                "-E",
                "-I",
                "-s",
                "-S",
                "-O",
                "-OO",
                "-q",
            ):
                i += 1
            if i + 1 >= len(args) or args[i].startswith("-"):
                return None
            cwd = Path(os.readlink(proc / "cwd"))
            script = (cwd / args[i]).resolve()
            kinds = {
                ROOT / "processing/run_processing.py": "decode",
                ROOT / "plotting/run_plotting.py": "analysis",
            }
            kind = kinds.get(script)
            if not kind:
                return None
            directory = (cwd / args[i + 1]).resolve()
            session_path = directory.parent in (
                self.base.resolve(),
                self.legacy_base.resolve(),
            ) and re.fullmatch(r"[0-9a-f]{16}", directory.name)
            try:
                rel = directory.relative_to(self.decoded.resolve()).parts
            except ValueError:
                rel = ()
            cache_path = (
                len(rel) in (4, 5)
                and rel[0] in ("NKDAQ", "RCDAQ")
                and re.fullmatch(r"run_[0-9]+", rel[1])
                and re.fullmatch(r"[0-9a-f]{16,32}", rel[2])
                and (
                    (len(rel) == 4 and rel[3] == "raw")
                    or (
                        len(rel) == 5
                        and rel[3] == "matched"
                        and re.fullmatch(r"[0-9a-f]{16,32}", rel[4])
                    )
                )
            )
            if not session_path and not (cache_path and kind == "decode"):
                return None
            stat = (proc / "stat").read_text().rsplit(")", 1)[1].split()
            if stat[0] == "Z":
                return None
            config = read(directory / "config.json")
            profile = config.get("profile", "Unknown DAQ")
            run = config.get("run", "?")
            mode = ("Live" if config["live"] else "Batch") if "live" in config else "Unknown mode"
            stage = "matching" if config.get("raw_dir") else kind
            label = "shared run data" if cache_path else "session " + directory.name
            command = f"{profile} · Run {run} · {mode} · {stage} · {label}"
            return dict(
                pid=int(pid),
                directory=str(directory),
                start_ticks=stat[19],
                session=directory.name,
                kind=kind,
                profile=profile,
                run=run,
                mode=mode,
                command=command,
                full_line=command,
            )
        except (OSError, ValueError, IndexError):
            return None

    def processes(self):
        # Find running processes even when session files are missing.
        self.children = [p for p in self.children if p.poll() is None]
        return sorted(
            (
                info
                for entry in Path("/proc").iterdir()
                if entry.name.isdecimal()
                if (info := self.process(entry.name))
            ),
            key=lambda p: (p["session"], p["kind"]),
        )

    def signal_process(self, info, sig):
        # Recheck process identity to avoid terminating a reused PID.
        fd = None
        try:
            if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
                fd = os.pidfd_open(info["pid"])
            current = self.process(info["pid"])
            if (
                not current
                or current["start_ticks"] != info["start_ticks"]
                or current["session"] != info["session"]
            ):
                return False
            if fd is not None:
                signal.pidfd_send_signal(fd, sig)
            else:
                os.kill(info["pid"], sig)
            return True
        except ProcessLookupError:
            return False
        finally:
            if fd is not None:
                os.close(fd)

    # Stop processing and plotting workers for all active DQM sessions.
    def stop_all(self, timeout=10):
        self.base.mkdir(parents=True, exist_ok=True)
        with self.lock, (self.base / ".control.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            targets = self.processes()
            errors = []
            for info in targets:
                try:
                    self.signal_process(info, signal.SIGTERM)
                except OSError as error:
                    errors.append(f"PID {info['pid']}: {error}")

            def remaining():
                return [
                    p
                    for p in targets
                    if (current := self.process(p["pid"]))
                    and current["start_ticks"] == p["start_ticks"]
                ]

            deadline = time.monotonic() + timeout
            while remaining() and time.monotonic() < deadline:
                time.sleep(0.1)
            for info in remaining():
                try:
                    self.signal_process(info, signal.SIGKILL)
                except OSError as error:
                    errors.append(f"PID {info['pid']}: {error}")
            deadline = time.monotonic() + 1
            while remaining() and time.monotonic() < deadline:
                time.sleep(0.05)
            left = remaining()
            stopped = len(targets) - len(left)
            for info in targets:
                if any(p["pid"] == info["pid"] for p in left):
                    continue
                d = Path(info["directory"])
                status_path = d / (info["kind"] + "_status.json")
                old = read(status_path)
                if d.is_dir() and old.get("status") not in (
                    "complete",
                    "error",
                    "paused",
                    "caught_up",
                ):
                    write(status_path, dict(old, status="stopped", updated=time.time()))
            self.children = [p for p in self.children if p.poll() is None]
            message = f"Stopped {stopped} DQM processes" if targets else "No running DQM processes"
            if left:
                message += f"; {len(left)} still running"
            if errors:
                message += "; " + "; ".join(errors)
            return dict(
                success=not left and not errors,
                message=message,
                killed_count=stopped,
                remaining=left,
            )

    def alive(self, d, kind):
        pid = read(d / (kind + "_process.json")).get("pid")
        if not isinstance(pid, int):
            return False
        try:
            args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        except OSError:
            return False
        script = ROOT / (
            "processing/run_processing.py" if kind == "decode" else "plotting/run_plotting.py"
        )
        return str(script).encode() in args and str(d).encode() in args

    # Launch processing or plotting workers independently of HTTP connections.
    def launch(self, d, kind, finite=False):
        if self.alive(d, kind):
            return
        script = ROOT / (
            "processing/run_processing.py" if kind == "decode" else "plotting/run_plotting.py"
        )
        argv = [shutil.which("python3", path=self.env["PATH"]), "-u", str(script), str(d)]
        if finite:
            argv.append("--finite")
        env = dict(self.env, PYTHONDONTWRITEBYTECODE="1")
        with (d / (kind + ".log")).open("ab") as log:
            proc = subprocess.Popen(
                argv,
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self.children = [p for p in self.children if p.poll() is None]
        self.children.append(proc)
        write(d / (kind + "_process.json"), dict(pid=proc.pid))

    def status(self, session=None):
        with self.lock:
            self.children = [p for p in self.children if p.poll() is None]
            explicit = session is not None
            session = session or read(self.base / "active.json").get("session")
            if not session:
                return dict(session=None)
            if not explicit and not any(
                (base / session / "config.json").is_file() for base in (self.base, self.legacy_base)
            ):
                return dict(session=None)
            d = self.directory(session)
            config = read(d / "config.json")
            data_dir = Path(config.get("data_dir", d))
            raw_dir = Path(config.get("raw_dir", data_dir))
            decode = read(data_dir / "decode_status.json", {"status": "starting"})

            if "input_progress" not in decode:
                decode = dict(decode, input_progress=input_progress(decode.get("inputs", [])))
            analysis = read(d / "analysis_status.json", {"status": "starting"})
            decoding = self.alive(data_dir, "decode")
            plotting = self.alive(d, "analysis")
            if not decoding and decode.get("status") in ("starting", "running", "waiting"):
                decode = dict(
                    decode,
                    status="error",
                    error="Decoder exited unexpectedly; inspect decode.log and Execute again after correcting the cause",
                )
            if not plotting and analysis.get("status") in (
                "starting",
                "waiting_for_decode",
                "replaying",
                "running",
                "waiting",
            ):
                analysis = dict(
                    analysis,
                    status="error",
                    error="Plotter exited unexpectedly; inspect analysis.log",
                )
            raw = decode_status(raw_dir)
            if data_dir != raw_dir:
                decode = dict(
                    decode,
                    inputs=raw.get("inputs", []),
                    input_progress=raw.get("input_progress", {}),
                    raw_status=raw.get("status", "starting"),
                )
            stopped = (d / "stopped.json").exists()
            if stopped:
                decoding = False
                analysis = dict(analysis, status="stopped")
            files = []
            p = Path(config["plot_dir"]) / config.get("plot_name", f'matched_{config["run"]}.root')
            if p.exists():
                st = p.stat()
                files = [
                    dict(
                        name="combined/" + p.resolve().relative_to(self.output).as_posix(),
                        type="root",
                        mtime_ns=st.st_mtime_ns,
                        size=st.st_size,
                        version=read(p.parent / "latest.json").get("version"),
                    )
                ]
            processing = decoding or (
                plotting
                and analysis.get("status")
                in ("starting", "waiting_for_decode", "replaying", "running", "waiting")
            )
            processing = processing and not stopped
            process_pid = (
                read(
                    (d if plotting else data_dir)
                    / ("analysis_process.json" if plotting else "decode_process.json")
                ).get("pid")
                if processing
                else None
            )
            return dict(
                cache=config.get("cache"),
                matching=config.get("matching", True),
                matching_reasons=config.get("matching_reasons", []),
                processing=processing,
                process_pid=process_pid,
                session=session,
                profile=config["profile"],
                run=config["run"],
                live=config["live"],
                decode=decode,
                raw_decode=raw,
                analysis=analysis,
                decoding=decoding,
                plotting=plotting,
                files=files,
            )

    # Reuse completed run caches and attach readers to active producers.
    def ensure_cache(self, directory, config, seed=None):
        original = directory
        replacement = read(original / "replacement.json").get("directory")
        if replacement:
            candidate = Path(replacement).resolve()
            if self.decoded.resolve() in candidate.parents:
                directory = candidate
        if complete_cache(directory):
            return directory, "reused"
        if self.alive(directory, "decode"):
            return directory, "shared"
        state = read(directory / "decode_status.json").get("status")
        if state in ("complete", "error"):
            directory = (
                directory.parent / (directory.name[:16] + uuid.uuid4().hex[:16])
                if directory.name != "raw"
                else directory.parent.with_name(directory.parent.name[:16] + uuid.uuid4().hex[:16])
                / "raw"
            )
        directory.mkdir(parents=True, exist_ok=True)
        seeded = False
        if not (directory / "config.json").exists():
            if seed and seed != directory:
                config = dict(config, seed_dir=str(seed))
                seeded = True
            write(directory / "config.json", config)
        else:
            config = read(directory / "config.json")
        write(directory / "decode_status.json", dict(status="starting"))
        self.launch(directory, "decode", not config["live"])
        if directory != original:
            write(original / "replacement.json", dict(directory=str(directory)))
        return (
            directory,
            "seeded"
            if seeded
            else "resumed"
            if (directory / "checkpoint.pkl").exists()
            else "created",
        )

    # Share raw decoding by run; keep plot settings and logs per execution.
    def start(self, request):
        self.base.mkdir(parents=True, exist_ok=True)
        with self.lock, (self.base / ".control.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            plan = self.plan(request)
            config = dict(plan["config"])
            live = bool(request.get("live"))
            raw = raw_config(config, live)
            run_dir = self.decoded / config["profile"] / f"run_{config['run']:05d}"
            raw_dir, reuse = self.ensure_cache(
                run_dir / digest(raw) / "raw", raw, seed_cache(run_dir, raw)
            )
            data_dir = raw_dir
            if config.get("matching", True):
                match = {
                    k: v
                    for k, v in config.items()
                    if k not in ("plot_dir", "plot_name", "matching_reasons")
                }
                match.update(raw_dir=str(raw_dir), live=live, timing=raw.get("timing", False))
                match["matcher_version"] = digest(
                    {
                        name: (ROOT / name).read_text()
                        for name in (
                            "matching/cached_pipeline.py",
                            "matching/trigger_matcher.py",
                            "matching/timestamp_matcher.py",
                            "storage/root_reader.py",
                        )
                    }
                )
                data_dir, _ = self.ensure_cache(raw_dir.parent / "matched" / digest(match), match)
            session = uuid.uuid4().hex[:16]
            d = self.base / session
            d.mkdir()
            config.update(
                live=live,
                raw_dir=str(raw_dir),
                data_dir=str(data_dir),
                cache=dict(mode=reuse, directory=str(raw_dir)),
                timing=raw.get("timing", False),
                plot_dir=str(
                    self.output / config["profile"] / f"run_{config['run']:05d}" / session
                ),
            )
            Path(config["plot_dir"]).mkdir(parents=True, exist_ok=True)
            write(d / "config.json", config)
            write(d / "analysis.json", plan["analysis"])
            write(d / "request.json", request)
            write(d / "analysis_status.json", dict(status="starting"))
            write(self.base / "active.json", dict(session=session))
            self.launch(d, "analysis")
            return self.status(session)

    def stop(self, session):
        with self.lock, (self.base / ".control.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            d = self.directory(session)
            config = read(d / "config.json")
            write(d / "stopped.json", dict(updated=time.time()))
            if self.alive(d, "analysis"):
                os.kill(read(d / "analysis_process.json")["pid"], signal.SIGTERM)
            # Keep shared decoding and matching workers alive for other plots.
            in_use = set()
            for other in self.base.iterdir():
                if other == d or not other.is_dir() or (other / "stopped.json").exists():
                    continue
                if self.alive(other, "analysis"):
                    c = read(other / "config.json")
                    in_use.update(c.get(key) for key in ("data_dir", "raw_dir"))
            for path in dict.fromkeys(
                (config.get("data_dir", str(d)), config.get("raw_dir", str(d)))
            ):
                if path not in in_use and self.alive(Path(path), "decode"):
                    os.kill(read(Path(path) / "decode_process.json")["pid"], signal.SIGTERM)
            return self.status(session)
