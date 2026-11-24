"""Correct NK/RC clock differences and match events by timestamp."""
from collections import deque
import numpy as np
from storage.event_data import Event


class TimeMatcher:
    def __init__(self, scale=0.99998982, tolerance=1.0, offset=None, auto_clock=True):
        self.scale = scale
        self.initial_scale = scale
        self.auto_clock = auto_clock
        self.clock_pairs = deque(maxlen=512)
        self.tolerance = tolerance
        self.offset = offset
        self.nk = deque()
        self.rc = deque()
        self.dropped_nk = 0
        self.dropped_rc = 0
        self.recent_offsets = deque(maxlen=32)
        self.matches = 0
        self.locked = offset is not None
        self.sync_pairs = 0

    def _synchronize(self, final=False):
        # Find initial offset candidates from inter-event time intervals.
        if min(len(self.nk), len(self.rc)) < 6:
            return False
        a = list(self.nk)[:128]
        b = list(self.rc)[:128]
        best = None
        candidates = []
        for i in range(min(24, len(a) - 5)):
            for j in range(min(24, len(b) - 5)):
                offset = a[i].time - b[j].time * self.scale
                x = i
                y = j
                residual = []
                pairs = []
                while x < len(a) and y < len(b):
                    delta = a[x].time - (b[y].time * self.scale + offset)
                    if abs(delta) <= self.tolerance:
                        residual.append(delta)
                        pairs.append((b[y].time, a[x].time))
                        x += 1
                        y += 1
                    elif delta < 0:
                        x += 1
                    else:
                        y += 1
                if len(residual) < 6:
                    continue
                score = (len(residual), -float(np.mean(np.abs(residual))), -i - j)
                candidate = (score, offset + float(np.median(residual)), len(residual), pairs)
                candidates.append(candidate)
                if best is None or score > best[0]:
                    best = candidate
        if best is None:
            return False
        # Leave synchronization unlocked when several offsets fit equally well.
        if any(
            abs(c[1] - best[1]) > 2 * self.tolerance and c[2] >= max(6, 0.85 * best[2])
            for c in candidates
        ):
            return False
        self.offset = best[1]
        self.sync_pairs = best[2]
        self.locked = True
        self.clock_pairs.extend(best[3])
        self._fit_clock()
        return True

    # Refine clock scale and offset using verified timestamp pairs.
    def _fit_clock(self):
        if not self.auto_clock or len(self.clock_pairs) < 32:
            return
        pairs = np.array(self.clock_pairs)
        x = pairs[:, 0]
        y = pairs[:, 1]
        if np.ptp(x) < 10000:
            return
        dx = x - x.mean()
        dy = y - y.mean()
        scale = float(np.dot(dx, dy) / np.dot(dx, dx))
        offset = float(np.median(y - scale * x))
        residual = y - (scale * x + offset)
        if abs(scale - self.initial_scale) > 1e-4 or np.max(np.abs(residual)) > self.tolerance:
            return
        self.scale = scale
        self.offset = offset
        self.recent_offsets.clear()

    # Join events only when corrected timestamps fall within tolerance.
    def drain(self, final=False):
        if not self.locked:
            if not final and min(len(self.nk), len(self.rc)) < 128:
                return []
            if not self._synchronize(final):
                return []
        result = []
        while self.nk and self.rc:
            n = self.nk[0]
            r = self.rc[0]
            delta = n.time - (r.time * self.scale + self.offset)
            if abs(delta) <= self.tolerance:
                self.nk.popleft()
                self.rc.popleft()
                self.matches += 1
                result.append(
                    Event(n.key, n.time, dict(n.waves, **r.materialize()), r.rc_timestamp, delta)
                )
                self.clock_pairs.append((r.time, n.time))
                self.offset = n.time - r.time * self.scale
                if self.matches % 64 == 0:
                    self._fit_clock()
            elif delta < 0:
                self.nk.popleft()
                self.dropped_nk += 1
            else:
                self.rc.popleft()
                self.dropped_rc += 1
        return result
