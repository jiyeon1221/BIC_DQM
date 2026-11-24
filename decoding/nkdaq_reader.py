"""Read complete NKDAQ records and assemble waveforms by trigger."""
from collections import deque
import os
import numpy as np
from storage.event_data import Event, Wave


class NKTail:
    def __init__(self, path, daq, mid, channels, reorder=1000):
        self.path = str(path)
        self.daq = daq
        self.mid = mid
        self.channels = channels
        self.offset = 0
        self.identity = None
        self.pending = {}
        self.ready = deque()
        self.maximum = -1
        self.closed = -1
        self.reorder = reorder
        self.fadc_length = None
        self.records = 0
        self.bad = 0
        self.late = 0
        self.duplicates = 0

    # Read complete records and defer incomplete tails until the next poll.
    def poll(self, budget=1024 * 1024):
        if not os.path.exists(self.path):
            return 0
        st = os.stat(self.path)
        identity = (st.st_dev, st.st_ino)
        if self.identity and self.identity != identity:
            raise RuntimeError("Input replaced: " + self.path)
        self.identity = identity
        if st.st_size < self.offset:
            raise RuntimeError("Input truncated: " + self.path)
        start = self.offset
        with open(self.path, "rb", buffering=1024 * 1024) as stream:
            while self.offset - start < budget:
                stream.seek(self.offset)
                prefix = stream.read(16 if self.daq == "NKFADC" else 32)
                if len(prefix) < (16 if self.daq == "NKFADC" else 32):
                    break
                if self.daq == "NKFADC":
                    if self.fadc_length is None:
                        lengths = [int.from_bytes(prefix[lane:16:4], "little") for lane in range(4)]
                        valid = [n for n in lengths if 32 < n <= 16384 and n % 2 == 0]
                        if not valid:
                            raise RuntimeError("No valid NKFADC header: " + self.path)
                        self.fadc_length = max(set(valid), key=valid.count)
                    length = self.fadc_length
                else:
                    length = int.from_bytes(prefix[:4], "little")
                if length <= 32 or length > (16384 if self.daq == "NKFADC" else 65536):
                    raise RuntimeError(f"Invalid {self.daq} record at {self.offset}: {length}")
                size = length * (4 if self.daq == "NKFADC" else 1)
                stream.seek(self.offset)
                data = stream.read(size)
                if len(data) < size:
                    break
                if self.daq == "NKFADC":
                    for lane in range(4):
                        block = data[lane::4]
                        if (
                            block[16] != lane + 1
                            or block[15] != self.mid
                            or int.from_bytes(block[:4], "little") != length
                        ):
                            self.bad += 1
                            continue
                        self._lane(block, True)
                else:
                    self._lane(data, False)
                self.offset += size
                self.records += 1
        self._release(False)
        return self.offset - start

    def _lane(self, data, fadc):
        ch = data[16]
        if ch not in self.channels:
            return
        if data[15] != self.mid or int.from_bytes(data[:4], "little") != len(data):
            self.bad += 1
            return
        trigger = int.from_bytes(data[7:11], "little")
        # NK timestamps use microseconds; one fine-clock tick is 0.008 microseconds.
        timestamp = int.from_bytes(data[26:32], "little") + data[25] * 0.008
        if trigger <= self.closed:
            self.late += 1
            return
        self.maximum = max(self.maximum, trigger)
        if fadc:
            adc = (np.frombuffer(data[32:], dtype="<u2") & 4095).astype(np.int16)
        else:
            stride = 4 if self.daq == "BIC" else 2
            if (len(data) - 32) % stride:
                self.bad += 1
                return
            adc = np.frombuffer(data[32:], dtype="<i2")[:: stride // 2].copy()
        event = self.pending.setdefault(trigger, Event(trigger, timestamp))
        name = self.channels[ch]
        if name in event.waves:
            self.duplicates += 1
            return
        event.waves[name] = Wave(trigger, timestamp, adc)

    def _release(self, final):
        # Emit ordered triggers only after the reorder window has passed.
        for key in sorted(self.pending):
            if not final and key > self.maximum - self.reorder:
                break
            self.ready.append(self.pending.pop(key))
            self.closed = key

    def finish(self):
        self._release(True)

    def tail_bytes(self):
        return max(0, os.path.getsize(self.path) - self.offset) if os.path.exists(self.path) else 0
