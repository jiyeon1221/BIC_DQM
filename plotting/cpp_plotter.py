"""Call the C++ plotters and publish completed ROOT snapshots."""
import ctypes
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import weakref
from storage.session_state import atomic_json

BASE = Path(__file__).resolve().parent
LIBRARY = BASE / "libdqm_plots.so"
_library = None


# Serialize library builds across concurrent sessions.
def build(force=False):
    sources = sorted(BASE.glob("*.C")) + sorted(BASE.glob("*.h"))
    with (BASE / ".build.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (
            not force
            and LIBRARY.exists()
            and LIBRARY.stat().st_mtime_ns >= max(p.stat().st_mtime_ns for p in sources)
        ):
            return LIBRARY
        flags = shlex.split(
            subprocess.check_output(["root-config", "--cflags", "--glibs"], text=True)
        )
        fd, name = tempfile.mkstemp(prefix=".libdqm_plots.", suffix=".so", dir=BASE)
        os.close(fd)
        try:
            subprocess.run(
                [
                    os.environ.get("CXX", "g++"),
                    "-O2",
                    "-shared",
                    "-fPIC",
                    *map(str, sorted(BASE.glob("*.C"))),
                    *flags,
                    "-o",
                    name,
                ],
                check=True,
            )
            os.replace(name, LIBRARY)
        finally:
            Path(name).unlink(missing_ok=True)
    return LIBRARY


def library():
    global _library
    if _library is None:
        _library = ctypes.CDLL(str(build()), mode=ctypes.RTLD_GLOBAL)
        _library.dqm_plot_create.argtypes = [ctypes.c_char_p]
        _library.dqm_plot_create.restype = ctypes.c_void_p
        _library.dqm_plot_error.argtypes = []
        _library.dqm_plot_error.restype = ctypes.c_char_p
        _library.dqm_plot_call.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        _library.dqm_plot_call.restype = ctypes.c_char_p
        _library.dqm_plot_destroy.argtypes = [ctypes.c_void_p]
        _library.dqm_plot_destroy.restype = None
    return _library


class Plots:
    def __init__(self, config, analysis):
        self.config = config
        self.analysis = analysis
        self.native = library()
        self.handle = self.native.dqm_plot_create(
            json.dumps(dict(config=config, analysis=analysis)).encode()
        )
        if not self.handle:
            raise ValueError(self.native.dqm_plot_error().decode())
        self._cleanup = weakref.finalize(self, self.native.dqm_plot_destroy, self.handle)
        self._call("statistics")

    def close(self):
        self._cleanup()
        self.handle = None

    def _call(self, operation, **data):
        if not self.handle:
            raise RuntimeError("Plotter is closed")
        result = json.loads(
            self.native.dqm_plot_call(
                self.handle, json.dumps(dict(operation=operation, **data)).encode()
            )
        )
        if "error" in result:
            raise RuntimeError(result["error"])
        for name in ("seen", "evaluated", "passed", "plotted"):
            setattr(self, name, result[name])

    def add(self, path):
        self._call("add", path=str(path))

    # Let C++ save ROOT objects; manage publication and snapshot retention here.
    def save(self):
        directory = Path(self.config["plot_dir"])
        tmp = directory / ".plots.root.partial"
        self._call("save", path=str(tmp), analysis=json.dumps(self.analysis))
        snapshots = directory / ".snapshots"
        snapshots.mkdir(exist_ok=True)
        version = "v" + str(time.time_ns())
        snapshot = snapshots / (version + ".root")
        os.replace(tmp, snapshot)
        link = directory / ".latest.root"
        if link.exists():
            link.unlink()
        os.link(snapshot, link)
        os.replace(
            link, directory / self.config.get("plot_name", f'matched_{self.config["run"]}.root')
        )
        atomic_json(
            directory / "latest.json",
            dict(
                version=version,
                revision=self.analysis["revision"],
                seen=self.seen,
                summary=dict(
                    method=self.analysis["method"],
                    type=self.analysis["type"],
                    has_aux_cut=bool(self.analysis["cuts"]),
                ),
            ),
        )
        for old in sorted(snapshots.glob("v*.root"))[:-10]:
            old.unlink()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(build(force=args.force))
