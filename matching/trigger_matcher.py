"""Join NKDAQ inputs by trigger ID."""
from storage.event_data import Event


class NKJoin:
    def __init__(self, required, reference=None):
        self.required = set(required)
        self.reference = reference
        self.dropped = 0
        self.emitted = 0

    # Merge equal triggers and reject events missing required channels.
    def drain(self, sources, final=False):
        result = []
        while all(s.ready for s in sources):
            target = max(s.ready[0].key for s in sources)
            for s in sources:
                while s.ready and s.ready[0].key < target:
                    s.ready.popleft()
                    self.dropped += 1
            if not all(s.ready for s in sources):
                break
            if any(s.ready[0].key != target for s in sources):
                continue
            parts = [s.ready.popleft() for s in sources]
            waves = {k: v for e in parts for k, v in e.waves.items()}
            if not self.required <= waves.keys():
                self.dropped += 1
                continue
            ref = waves.get(self.reference) if self.reference else None
            result.append(Event(target, ref.time if ref else parts[0].time, waves))
            self.emitted += 1
        if final:
            for s in sources:
                self.dropped += len(s.ready)
                s.ready.clear()
        return result
