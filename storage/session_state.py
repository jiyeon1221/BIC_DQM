"""Atomically save status JSON and recovery checkpoints."""
import json
import os
import pickle


def atomic_json(path, value):
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(json.dumps(value, allow_nan=False))
    os.replace(tmp, path)


def checkpoint(path, state):
    tmp = path.with_name("." + path.name + ".tmp")
    with tmp.open("wb") as stream:
        pickle.dump(state, stream, protocol=5)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


class CheckpointReader(pickle.Unpickler):
    # Resolve class names from checkpoints created before the package split.
    def find_class(self, module, name):
        modules = {
            ("core", "Wave"): "storage.event_data",
            ("core", "Event"): "storage.event_data",
            ("core", "NKTail"): "decoding.nkdaq_reader",
            ("core", "NKJoin"): "matching.trigger_matcher",
            ("core", "TimeMatcher"): "matching.timestamp_matcher",
            ("worker", "Pipeline"): "processing.event_pipeline",
            ("__main__", "Pipeline"): "processing.event_pipeline",
        }
        previous_modules = {
            "decoding.nk": "decoding.nkdaq_reader",
            "matching.trigger": "matching.trigger_matcher",
            "matching.clock": "matching.timestamp_matcher",
            "processing.pipeline": "processing.event_pipeline",
            "storage.events": "storage.event_data",
        }
        module = previous_modules.get(module, module)
        return super().find_class(modules.get((module, name), module), name)


def load_checkpoint(path):
    with path.open("rb") as stream:
        return CheckpointReader(stream).load()
