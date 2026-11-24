"""Supply decode batches from input queues and match only when required."""
from collections import deque
from pathlib import Path
from types import SimpleNamespace
import os
import time
import numpy as np
from decoding.nkdaq_reader import NKTail
from decoding.rcdaq_decoder import rc_decoder
from matching.trigger_matcher import NKJoin
from matching.timestamp_matcher import TimeMatcher
from storage.event_data import Event
from processing.input_progress import input_progress


class Pipeline:
    def __init__(self, config):
        self.config = config
        self.independent = not config.get("matching", True)
        self.batch_size = config.get("decode_batch_size", 1000)
        self.batch_decoded = self.decoded_total = self.decode_batches = 0
        self.source_counts = {}
        self.cursor = 0
        rows = config["mapping"]
        capture = set(config["capture"])
        groups = {}
        for row in rows:
            if row["name"] in capture and row["daq"] != "GCROC":
                groups.setdefault((row["daq"], row["mid"]), {})[row["ch"]] = row["name"]
        self.sources = []
        for (daq, mid), channels in sorted(groups.items()):
            token = "FADC" if daq == "NKFADC" else daq
            path = Path(config["nk_path"]) / f"Run_{config['run']:05d}_{token}_{mid}.dat"
            self.sources.append(NKTail(path, daq, mid, channels, config["reorder"]))
        # Keep unread input queues separate from matching queues.
        self.join_inputs = [SimpleNamespace(ready=deque()) for _ in self.sources]
        self.nk_ended = [False] * len(self.sources)
        self.rc_rows = [r for r in rows if r["daq"] == "GCROC" and r["name"] in capture]
        self.rc_ready = deque()
        self.rc_ended = False
        nk_names = {r["name"] for r in rows if r["daq"] != "GCROC"}
        self.join = NKJoin(set(config["required"]) & nk_names, config.get("reference"))
        self.matcher = TimeMatcher(
            config["clock_scale"],
            config["tolerance_us"],
            config.get("offset_us"),
            config.get("auto_clock", True),
        )
        self.rc_offset = self.rc_count = self.rc_events = 0
        self.rc_identity = None
        self.end_run = False
        self.pending = []
        self.chunks = []
        self.committed = self.sequence = 0
        self.finished = False

    @property
    def rc_path(self):
        return Path(self.config["rc_path"]) / f"2608CERN_ROC_0-{self.config['run']:08d}-0000.evt"

    # Read input files into per-DAQ decode queues.
    def read_inputs(self, finite):
        changed = 0
        limit = self.config["queue_limit"]
        for i, source in enumerate(self.sources):
            waiting = len(source.ready) + len(source.pending) + len(self.join_inputs[i].ready)
            if waiting < limit and (self.independent or len(self.matcher.nk) < limit):
                changed += source.poll()
            self.nk_ended[i] = finite and Path(source.path).exists() and not source.tail_bytes()
            if self.nk_ended[i]:
                source.finish()
        if (
            self.rc_rows
            and not self.rc_ready
            and len(self.matcher.rc) < limit
            and self.rc_path.exists()
        ):
            stat = self.rc_path.stat()
            identity = (stat.st_dev, stat.st_ino)
            if self.rc_identity and identity != self.rc_identity:
                raise RuntimeError("RC input replaced")
            self.rc_identity = identity
            block = self.decode(
                str(self.rc_path),
                self.rc_offset,
                self.config["run"],
                self.channel_vector,
                self.config.get("timing", False),
            )
            changed += int(block.next) - self.rc_offset
            self.rc_offset = int(block.next)
            self.rc_events += block.events
            self.end_run = self.end_run or block.endRun
            names = tuple(r["name"] for r in self.rc_rows)
            for wave in block.waves:
                shape = (len(names), wave.samples)
                adc = np.asarray(wave.adc, dtype=np.int16).reshape(shape).copy()
                toa = tot = None
                if self.config.get("timing"):
                    toa = np.asarray(wave.toa, dtype=np.int16).reshape(shape).copy()
                    tot = np.asarray(wave.tot, dtype=np.int16).reshape(shape).copy()
                stamp = int(wave.timestamp)
                self.rc_ready.append(
                    Event(
                        self.rc_count,
                        stamp / 160.0,
                        rc_timestamp=stamp,
                        rc_adc=adc,
                        rc_names=names,
                        rc_toa=toa,
                        rc_tot=tot,
                    )
                )
                self.rc_count += 1
        self.rc_ended = (
            finite
            and bool(self.rc_rows)
            and self.rc_path.exists()
            and self.rc_path.stat().st_size == self.rc_offset
        )
        return changed

    def feed_batch(self):
        """Read inputs round-robin, supplying up to 1,000 source events per batch."""
        inputs = [
            (f"{s.daq}:{s.mid}", s.ready, j.ready) for s, j in zip(self.sources, self.join_inputs)
        ]
        if self.rc_rows:
            inputs.append(("GCROC", self.rc_ready, self.matcher.rc))
        fed = 0
        while inputs and self.batch_decoded < self.batch_size:
            admitted = False
            for _ in inputs:
                i = self.cursor % len(inputs)
                self.cursor = (i + 1) % len(inputs)
                name, ready, target = inputs[i]
                if not ready or (
                    not self.independent and len(target) >= self.config["queue_limit"]
                ):
                    continue
                event = ready.popleft()
                event.source = name
                event.source_event = self.source_counts.get(name, 0)
                self.source_counts[name] = event.source_event + 1
                if self.independent:
                    event.materialize()
                    self.pending.append(event)
                else:
                    target.append(event)
                self.decoded_total += 1
                self.batch_decoded += 1
                fed += 1
                admitted = True
                break
            if not admitted:
                break
        return fed

    # Join triggers and match NK/RC timestamps unless analysis uses independent inputs.
    def match(self):
        if self.independent:
            return
        if self.sources:
            self.matcher.nk.extend(self.join.drain(self.join_inputs))
        # Discard remaining events that cannot match an exhausted input.
        nk_done = bool(self.sources) and any(
            ended and not source.ready and not joined.ready
            for ended, source, joined in zip(self.nk_ended, self.sources, self.join_inputs)
        )
        if nk_done:
            self.join.drain(self.join_inputs, final=True)
        rc_done = self.rc_ended and not self.rc_ready
        if self.sources and self.rc_rows:
            self.pending.extend(self.matcher.drain(final=nk_done or rc_done))
            if not self.matcher.locked and min(len(self.matcher.nk), len(self.matcher.rc)) >= 128:
                raise RuntimeError(
                    "Cannot establish NK/RC clock alignment; no unverified pairs are published"
                )
            if nk_done and not self.matcher.nk:
                self.matcher.dropped_rc += len(self.matcher.rc)
                self.matcher.rc.clear()
            if rc_done and not self.matcher.rc:
                self.matcher.dropped_nk += len(self.matcher.nk)
                self.matcher.nk.clear()
        elif self.sources:
            self.pending.extend(self.matcher.nk)
            self.matcher.nk.clear()
        else:
            for event in self.matcher.rc:
                event.materialize()
            self.pending.extend(self.matcher.rc)
            self.matcher.rc.clear()

    def step(self, final=False, report=None):
        if report:
            report("reading")
        changed = self.read_inputs(finite=final)
        if report:
            report("collecting" if self.independent else "matching")
        changed += self.feed_batch()
        self.match()
        return changed

    def exhausted(self):
        return (
            all(self.nk_ended)
            and all(not s.ready for s in self.sources)
            and (not self.rc_rows or (self.rc_ended and not self.rc_ready))
        )

    def attach(self):
        if self.rc_rows:
            from storage.root_writer import root

            self.decode = rc_decoder()
            self.channel_vector = root().std.vector("int")()
            for row in self.rc_rows:
                self.channel_vector.push_back(row["ch"])

    def __getstate__(self):
        return {k: v for k, v in self.__dict__.items() if k not in ("decode", "channel_vector")}

    # Report the current stage, throughput, queues, and input progress.
    def snapshot(self, status):
        inputs = [
            dict(
                path=s.path,
                bytes=s.offset,
                records=s.records,
                waiting=len(s.pending) + len(s.ready) + len(j.ready),
                late=s.late,
                bad=s.bad,
                duplicates=s.duplicates,
            )
            for s, j in zip(self.sources, self.join_inputs)
        ]
        if self.rc_rows:
            inputs.append(
                dict(
                    path=str(self.rc_path),
                    bytes=self.rc_offset,
                    records=self.rc_count,
                    waiting=len(self.rc_ready) + len(self.matcher.rc),
                )
            )
        return dict(
            status=status,
            phase=getattr(self, "phase", "reading"),
            input_progress=input_progress(inputs),
            updated=time.time(),
            pid=os.getpid(),
            matching=not self.independent,
            matched=self.committed + len(self.pending),
            committed=self.committed,
            decoded_records=self.decoded_total,
            source_counts=self.source_counts,
            decode_batches=self.decode_batches,
            batch_decoded=self.batch_decoded,
            batch_size=self.batch_size,
            chunks=len(self.chunks),
            pending_chunk=len(self.pending),
            decoded_nk=sum(n for key, n in self.source_counts.items() if key != "GCROC"),
            joined_nk=self.join.emitted,
            decoded_rc=self.rc_count,
            nk_unmatched=self.matcher.dropped_nk,
            nk_join_dropped_parts=self.join.dropped,
            rc_unmatched=self.matcher.dropped_rc,
            waiting_nk=len(self.matcher.nk),
            waiting_rc=len(self.matcher.rc),
            clock_matching=bool(self.sources and self.rc_rows and not self.independent),
            sync_locked=self.matcher.locked,
            sync_pairs=self.matcher.sync_pairs,
            clock_offset_us=self.matcher.offset,
            clock_scale=self.matcher.scale,
            rc_bytes=self.rc_offset,
            rc_end_seen=self.end_run,
            inputs=inputs,
        )
