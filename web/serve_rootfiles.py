#!/usr/bin/env python3
# 사용법: python3 serve_rootfiles.py [--port 8000] [--host 0.0.0.0]

import argparse
import json
import os
import re
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUN_DIR = os.path.realpath(os.path.join(BASE_DIR, "..", "analysis"))
ROOT_DIR = os.path.realpath(os.path.join(BASE_DIR, "..", "output"))

FORBIDDEN_COMMANDS = ["rm", "cd"]
MAPPING_FILE = os.path.realpath(os.path.join(BASE_DIR, "..", "mapping", "mapping_CERN2026.h"))
MAPPING_ROW = re.compile(r'\{\s*"(\w+)"\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*"([^"]+)"')

DQM_EXECUTABLES = {"draw_avg", "draw_heatmap", "draw_intADC", "draw_overlay", "draw_peakADC",
                   "draw_waveform", "draw_singleWaveform", "draw_AUX", "DWC", "DWC_calibration", "hodoscope"}

CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript",
                 ".css": "text/css", ".png": "image/png", ".gif": "image/gif",
                 ".pdf": "application/pdf", ".json": "application/json"}

current_process = None
process_lock = threading.Lock()


def load_env():
    out = subprocess.run(["bash", "-c", f"source '{os.path.join(BASE_DIR, 'envset.sh')}' >/dev/null 2>&1; env -0"],
                         capture_output=True, check=True).stdout
    env = {}
    for item in out.split(b"\0"):
        if b"=" in item:
            k, v = item.split(b"=", 1)
            env[k.decode()] = v.decode()
    return env


ENV = load_env()


def safe_join(base, rel):
    path = os.path.realpath(os.path.join(base, rel))
    return path if path == os.path.realpath(base) or path.startswith(os.path.realpath(base) + os.sep) else None


def is_forbidden(command):
    parts = command.split()
    return bool(parts) and parts[0] in FORBIDDEN_COMMANDS


def find_dqm_processes():
    processes = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if argv and os.path.basename(argv[0]) in DQM_EXECUTABLES:
            processes.append({"pid": pid, "command": " ".join(argv), "full_line": " ".join(argv)})
    return processes


def kill_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
    except ProcessLookupError:
        pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if "/files" not in self.path and "/process_status" not in self.path and "/api/system-info" not in self.path:
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

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlparse(self.path)
        path = unquote(url.path)

        if path == "/":
            return self.send_file(os.path.join(BASE_DIR, "index.html"))
        if path.startswith("/output/"):
            return self.send_file(safe_join(ROOT_DIR, path[len("/output/"):]), no_cache=True)
        if path == "/files":
            return self.list_files()
        if path == "/execute_stream":
            return self.execute_stream(parse_qs(url.query).get("command", [""])[0])
        if path == "/process_status":
            with process_lock:
                running = current_process is not None and current_process.poll() is None
                return self.send_json({"running": True, "pid": current_process.pid} if running else {"running": False})
        if path == "/find_monit_processes":
            procs = find_dqm_processes()
            return self.send_json({"success": True, "processes": procs, "count": len(procs)})
        if path == "/channels":
            return self.list_channels()
        if path == "/api/system-info":
            return self.system_info()
        return self.send_file(safe_join(BASE_DIR, path.lstrip("/")))

    def list_files(self):
        files_info = []
        for dirpath, _, filenames in os.walk(ROOT_DIR):
            for f in filenames:
                if f.startswith(".") or not f.endswith((".root", ".gif")):
                    continue
                full = os.path.join(dirpath, f)
                try:
                    stat = os.stat(full)
                except OSError:
                    continue
                files_info.append({"name": os.path.relpath(full, ROOT_DIR),
                                   "mtime": stat.st_mtime, "size": stat.st_size,
                                   "type": "gif" if f.endswith(".gif") else "root"})
        files_info.sort(key=lambda x: x["mtime"], reverse=True)
        self.send_json(files_info)

    def list_channels(self):
        try:
            with open(MAPPING_FILE) as f:
                text = re.sub(r"//.*", "", f.read())
        except OSError as e:
            return self.send_json({"error": str(e)}, 500)
        names = [m.group(4) for m in MAPPING_ROW.finditer(text)]
        self.send_json({"channels": names})

    def system_info(self):
        try:
            import psutil
            mem = psutil.virtual_memory()
            self.send_json({"memory": {"used": round(mem.used / 1024 ** 3, 2), "total": round(mem.total / 1024 ** 3, 2),
                                       "percent": mem.percent},
                            "cpu": {"percent": psutil.cpu_percent(interval=1)}})
        except ImportError:
            self.send_json({"memory": {"used": "N/A", "total": "N/A", "percent": "N/A"}, "cpu": {"percent": "N/A"}})

    def sse(self, kind, content):
        self.wfile.write(f"data: {json.dumps({'type': kind, 'content': content})}\n\n".encode())
        self.wfile.flush()

    def execute_stream(self, command):
        global current_process
        if not command or is_forbidden(command):
            msg = "No command provided" if not command else \
                f"Command not allowed for security reasons. Forbidden: {', '.join(FORBIDDEN_COMMANDS)}"
            body = f"data: {json.dumps({'type': 'error', 'content': msg})}\n\n".encode()
            self.send_response(400 if not command else 403)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.close_connection = True

        proc = None
        try:
            with process_lock:
                proc = current_process = subprocess.Popen(
                    command, shell=True, executable="/bin/bash", cwd=RUN_DIR, env=ENV,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
            self.sse("command", f"$ {command}")

            buffer = ""
            waiting = False
            while True:
                b = proc.stdout.read(1)
                if not b:
                    break
                ch = b.decode(errors="replace")
                buffer += ch
                if buffer.endswith("\x1b[F"):
                    waiting = True
                    continue
                if waiting and (ch in "\r\n" or buffer.endswith("\x1b[0m")):
                    self.sse("output", buffer.rstrip())
                    buffer, waiting = "", False
                elif ch == "\r" and not waiting:
                    self.sse("output", buffer)
                    buffer = ""
                elif ch == "\n" and not waiting:
                    if buffer.strip():
                        self.sse("output", buffer.rstrip("\n"))
                    buffer = ""
                elif len(buffer) > 1000:
                    self.sse("output", buffer)
                    buffer, waiting = "", False
            if buffer:
                self.sse("output", buffer)
            proc.wait()
            self.sse("complete", f"Command exited with code: {proc.returncode}")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self.sse("error", f"Error: {e}")
            except OSError:
                pass
            if proc and proc.poll() is None:
                kill_group(proc)
        finally:
            with process_lock:
                if current_process is proc and proc and proc.poll() is not None:
                    current_process = None

    def do_POST(self):
        global current_process
        path = urlparse(self.path).path
        data = self.read_json()

        if path == "/kill_process":
            with process_lock:
                proc = current_process
            if proc is None or proc.poll() is not None:
                return self.send_json({"success": False, "message": "No running process to kill"})
            kill_group(proc)
            return self.send_json({"success": True, "message": "Process terminated successfully"})

        if path == "/kill_all_monit":
            procs = find_dqm_processes()
            if not procs:
                return self.send_json({"success": True, "message": "No DQM processes found", "killed_count": 0})
            killed, failed = [], []
            for p in procs:
                pid = int(p["pid"])
                try:
                    os.kill(pid, signal.SIGTERM)
                    killed.append(pid)
                except OSError:
                    failed.append(pid)
            time.sleep(0.5)
            for pid in killed:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            msg = f"Killed {len(killed)} DQM process(es)" + (f", failed to kill: {failed}" if failed else "")
            return self.send_json({"success": True, "message": msg, "killed_count": len(killed),
                                   "failed_count": len(failed), "killed_pids": killed, "failed_pids": failed})

        self.send_text("Not found", 404)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    print("✅ Server starting...")
    print(f"📁 Serving ROOT files from: {ROOT_DIR}")
    print(f"🌐 Serving web files from: {BASE_DIR}")
    print(f"💻 Command execution enabled (forbidden: {', '.join(FORBIDDEN_COMMANDS)}), commands run in {RUN_DIR}")
    print(f"🔧 ROOTSYS: {ENV.get('ROOTSYS', '<not set>')}")
    print(f"🔧 DQM_DATA_PATH: {ENV.get('DQM_DATA_PATH', '<not set>')}")
    consts = os.path.join(RUN_DIR, "DWC_calibration_constants.txt")
    print(f"🔧 DWC constants: {consts} {'✅' if os.path.isfile(consts) else '❌ missing (DWC positions uncalibrated)'}")
    print(f"✅ Server ready on http://{args.host}:{args.port}")
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
