#!/usr/bin/env python3
"""Serve the DQM viewer, command interface, and process-control API."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from processing.channel_selection import DQM_ROOT, load_mapping

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.environ.get("DQM_WEB_OUTPUT_PATH", str(DQM_ROOT / "output/plot"))).resolve()
FILE_ROOTS = {
    "combined": OUTPUT_DIR,
    "NKDAQ": DQM_ROOT.parent / "analysis/NKDAQ/output",
    "RCDAQ": DQM_ROOT.parent / "analysis/RCDAQ/output",
}
ASSETS = {name: BASE_DIR / "vendor" / name for name in ("jsroot.js", "gif.js")}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript",
    ".css": "text/css",
    ".png": "image/png",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
    ".json": "application/json",
}


def load_env():
    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -e; source "$1" >/dev/null 2>&1; env -0',
            "dqm-env",
            str(BASE_DIR / "envset.sh"),
        ],
        capture_output=True,
        check=True,
    )
    return dict(item.decode().split("=", 1) for item in result.stdout.split(b"\0") if b"=" in item)


ENV = load_env()
from processing.session_manager import Controller

LIVE = Controller(ENV, OUTPUT_DIR)


def safe_join(base, rel):
    base = Path(base).resolve()
    path = (base / rel).resolve()
    return str(path) if path == base or base in path.parents else None


def plot_summary(path, namespace, parts):
    # Prefer metadata for the published plot, not a newer replot request.
    if namespace != "combined" or len(parts) != 4:
        return None

    def read_json(path):
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return {}

    latest = read_json(path.parent / "latest.json")
    if isinstance(latest.get("summary"), dict):
        return latest["summary"]
    session = parts[2]
    if not re.fullmatch(r"[0-9a-f]{16}", session):
        return None
    analysis = read_json(LIVE.base / session / "analysis.json") or read_json(
        DQM_ROOT / "output/sessions" / session / "analysis.json"
    )
    if not analysis or analysis.get("revision") != latest.get("revision"):
        return None
    return dict(
        method=analysis.get("method", ""),
        type=analysis.get("type", ""),
        has_aux_cut=bool(analysis.get("cuts")),
    )


def list_output_files():
    result = []
    for namespace, root in FILE_ROOTS.items():
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.suffix not in (".root", ".gif") or not p.is_file():
                continue
            if any(part.startswith(".") for part in p.relative_to(root).parts):
                continue
            if not safe_join(root, str(p.relative_to(root))):
                continue
            stat = p.stat()
            rel = p.relative_to(root).as_posix()
            parts = rel.split("/")
            profile = parts[0] if namespace == "combined" else namespace
            reader = parts[1] if namespace == "combined" and len(parts) > 1 else namespace
            result.append(
                dict(
                    name=namespace + "/" + rel,
                    mtime=stat.st_mtime,
                    mtime_ns=stat.st_mtime_ns,
                    size=stat.st_size,
                    type=p.suffix[1:],
                    profile=profile,
                    reader=reader,
                    analysis=plot_summary(p, namespace, parts),
                )
            )
    return sorted(result, key=lambda x: x["mtime_ns"], reverse=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if urlparse(self.path).path not in ("/files", "/process_status", "/api/system-info"):
            super().log_message(fmt, *args)

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, status):
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def send_file(self, path, no_cache=False):
        if not path or not os.path.isfile(path):
            return self.send_text(f"File {self.path} not found", 404)
        size = os.path.getsize(path)
        ctype = CONTENT_TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
        start, end, status = 0, size - 1, 200
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            first = rng[6:].split(",")[0]
            a, _, b = first.partition("-")
            try:
                if a:
                    start = int(a)
                    if b:
                        end = min(int(b), size - 1)
                elif b:
                    start = max(0, size - int(b))
            except ValueError:
                pass
            if start >= size or start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if no_cache:
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                data = f.read(min(65536, remaining))
                if not data:
                    break
                self.wfile.write(data)
                remaining -= len(data)

    def system_info(self):
        try:
            import psutil

            mem = psutil.virtual_memory()
            self.send_json(
                {
                    "memory": {
                        "used": round(mem.used / 1024**3, 2),
                        "total": round(mem.total / 1024**3, 2),
                        "percent": mem.percent,
                    },
                    "cpu": {"percent": psutil.cpu_percent(interval=1)},
                }
            )
        except ImportError:
            self.send_json(
                {
                    "memory": {"used": "N/A", "total": "N/A", "percent": "N/A"},
                    "cpu": {"percent": "N/A"},
                }
            )

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlparse(self.path)
        path = unquote(url.path)
        query = parse_qs(url.query)
        if path == "/":
            return self.send_file(str(BASE_DIR / "index.html"))
        if path.lstrip("/") in ASSETS:
            return self.send_file(str(ASSETS[path.lstrip("/")]))
        if path.startswith("/output/"):
            namespace, _, rel = path[len("/output/") :].partition("/")
            resolved = safe_join(FILE_ROOTS[namespace], rel) if namespace in FILE_ROOTS else None
            version = query.get("v", [""])[0]
            if version:
                if (
                    not resolved
                    or namespace != "combined"
                    or not re.fullmatch(r"v[0-9]{16,22}", version)
                ):
                    return self.send_text("Invalid snapshot", 400)
                resolved = str(Path(resolved).parent / ".snapshots" / (version + ".root"))
            return self.send_file(resolved, no_cache=True)
        if path == "/files":
            return self.send_json(list_output_files())
        if path == "/live/status":
            try:
                return self.send_json(LIVE.status(query.get("session", [None])[0]))
            except (ValueError, OSError) as e:
                return self.send_json({"error": str(e)}, 400)
        if path == "/channels":
            try:
                profiles = {name: load_mapping(name) for name in ("NKDAQ", "RCDAQ")}
                return self.send_json({"profiles": profiles})
            except (OSError, ValueError) as e:
                return self.send_json({"error": str(e)}, 400)
        if path == "/api/system-info":
            return self.system_info()
        if path == "/process_status":
            live = LIVE.status()
            return self.send_json(
                dict(
                    running=live.get("processing", False),
                    pid=live.get("process_pid"),
                    profile=live.get("profile"),
                )
            )
        if path == "/find_monit_processes":
            processes = LIVE.processes()
            return self.send_json(dict(success=True, processes=processes, count=len(processes)))
        if path == "/execute_stream":
            return self.send_json(
                {
                    "error": "Direct raw analysis is disabled in the web UI. Use Command Builder for automatic DQM processing."
                },
                410,
            )
        if path in ("/command_builder.js", "/session_monitor.js", "/waveform_viewer.js"):
            return self.send_file(str(BASE_DIR / path.lstrip("/")))
        return self.send_text("Not found", 404)

    def do_POST(self):
        path = urlparse(self.path).path
        data = self.read_json()
        if path == "/plan":
            try:
                return self.send_json(LIVE.plan(data))
            except (ValueError, KeyError, TypeError) as e:
                return self.send_json({"error": str(e)}, 400)
        if path.startswith("/live/"):
            try:
                if path == "/live/start":
                    result = LIVE.start(data)
                elif path == "/live/stop":
                    result = LIVE.stop(data.get("session"))
                else:
                    return self.send_text("Not found", 404)
                return self.send_json(result)
            except (ValueError, KeyError, TypeError, OSError) as e:
                return self.send_json({"error": str(e)}, 400)
        if path == "/kill_all_monit":
            try:
                return self.send_json(LIVE.stop_all())
            except OSError as e:
                return self.send_json(dict(success=False, message=str(e)), 500)
        if path == "/kill_process":
            live = LIVE.status()
            running = live.get("processing", False)
            if running:
                LIVE.stop(live["session"])
            return self.send_json(
                dict(
                    success=True,
                    message="DQM session stopping" if running else "No running DQM job",
                    killed_count=int(running),
                )
            )
        return self.send_text("Not found", 404)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    print(f"Unified NKDAQ / RCDAQ DQM: http://{args.host}:{args.port}", flush=True)
    print(f'Mappings: {DQM_ROOT / "mapping"}; output: {OUTPUT_DIR}', flush=True)
    print(f'NKDAQ data: {ENV.get("DQM_DATA_PATH")}', flush=True)
    print(f'RCDAQ data: {ENV.get("RCDAQ_DATA_PATH")}', flush=True)
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
