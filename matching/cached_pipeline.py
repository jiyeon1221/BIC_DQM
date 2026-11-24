"""Match required inputs from the shared decoded ROOT cache."""
from collections import deque
import json
from pathlib import Path
from processing.event_pipeline import Pipeline
from storage.root_reader import read_events
from storage.decoded_cache import decode_status


def read(path, default=None):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default or {}


class CachedPipeline(Pipeline):
    def __init__(self, config):
        super().__init__(config)
        self.raw_dir = Path(config["raw_dir"])
        self.raw_chunk = 0
        self.raw_positions = {}
        self.raw_buffers = {}
        self.raw_status = {}

    def attach(self):
        pass

    def read_inputs(self, finite):
        self.raw_status = decode_status(self.raw_dir)
        if self.raw_status.get("status") in ("error", "stopped", "paused"):
            raise RuntimeError(
                "Decoded input stopped: " + self.raw_status.get("error", self.raw_status["status"])
            )
        chunks = read(self.raw_dir / "manifest.json", {"chunks": []})["chunks"]
        changed = 0
        sources = {
            f"{s.daq}:{s.mid}": (s.ready, j.ready) for s, j in zip(self.sources, self.join_inputs)
        }
        if self.rc_rows:
            sources["GCROC"] = (self.rc_ready, self.matcher.rc)
        ended = {}
        # Track each input cursor separately so a long tail cannot block other inputs.
        for source, (ready, waiting) in sources.items():
            position = self.raw_positions.get(source, 0)
            buffer = self.raw_buffers.setdefault(source, deque())
            room = self.config["queue_limit"] - len(ready) - len(waiting)
            if room > 0 and not buffer and position < len(chunks):
                chunk = chunks[position]
                if "sources" not in chunk or source in chunk["sources"]:
                    buffer.extend(
                        read_events(
                            self.raw_dir / chunk["name"], set(self.config["capture"]), source
                        )
                    )
                position += 1
                changed += 1
            while buffer and room > 0:
                ready.append(buffer.popleft())
                if source == "GCROC":
                    self.rc_count += 1
                changed += 1
                room -= 1
            self.raw_positions[source] = position
            ended[source] = (
                self.raw_status.get("status") == "complete"
                and position == len(chunks)
                and not buffer
            )
        self.raw_chunk = min(self.raw_positions.values(), default=0)
        self.nk_ended = [ended[f"{s.daq}:{s.mid}"] for s in self.sources]
        self.rc_ended = ended.get("GCROC", False)
        return changed

    def snapshot(self, status):
        result = super().snapshot(status)
        result.update(
            inputs=self.raw_status.get("inputs", []),
            input_progress=self.raw_status.get("input_progress", {}),
            raw_chunks_read=self.raw_chunk,
            raw_status=self.raw_status.get("status", "starting"),
        )
        return result
