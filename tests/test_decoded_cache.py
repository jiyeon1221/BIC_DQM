"""Verify run-cache reuse and matching from stored raw waveforms."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from storage.decoded_cache import digest, raw_config, complete_cache
from storage.event_data import Event, Wave
from storage.root_writer import write_chunk
from storage.root_reader import read_events
from matching.cached_pipeline import CachedPipeline
import test_streaming


class DecodedCacheTests(unittest.TestCase):
    def test_analysis_changes_reuse_but_inputs_mapping_and_decoder_invalidate(self):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            config = test_streaming.StreamingTest.two_inputs(d)
            for mid in (41, 42):
                (d / f"Run_00001_BIC_{mid}.dat").write_bytes(b"raw")
            first = raw_config(dict(config, matching=False, capture=["A"], required=["A"]), False)
            changed_plot = raw_config(
                dict(config, timing=True, plot_name="other.root", required=["B"], reference="A"),
                False,
            )
            self.assertEqual(first, changed_plot)
            self.assertEqual(first["capture"], ["A", "B"])
            (d / "Run_00001_BIC_41.dat").write_bytes(b"more raw")
            self.assertNotEqual(digest(first), digest(raw_config(config, False)))
            config["mapping"][0]["ch"] = 2
            second = digest(raw_config(config, False))
            config["mapping"][0]["ch"] = 1
            self.assertNotEqual(second, digest(raw_config(config, False)))
            with patch("storage.decoded_cache.decoder_version", return_value="changed decoder"):
                self.assertNotEqual(digest(first), digest(raw_config(config, False)))

    def test_live_growth_keeps_the_same_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            config = test_streaming.StreamingTest.two_inputs(d)
            path = d / "Run_00001_BIC_41.dat"
            path.write_bytes(b"first")
            before = raw_config(config, True)
            with path.open("ab") as stream:
                stream.write(b"next")
            self.assertEqual(before, raw_config(config, True))

    def test_root_roundtrip_preserves_rc_timing_and_nk_identifiers(self):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            config = test_streaming.StreamingTest.two_inputs(d)
            config["mapping"][1].update(name="RC", daq="GCROC", mid=-1, ch=139)
            config.update(matching=False, capture=["A", "RC"], timing=True)
            adc = np.arange(24, dtype=np.int16)
            toa, tot = adc + 100, adc + 200
            events = [
                Event(7, 12.5, {"A": Wave(7, 12.5, adc)}, source="BIC:41", source_event=3),
                Event(
                    0,
                    17.0,
                    {"RC": Wave(0, 17.0, adc, toa, tot)},
                    rc_timestamp=2720,
                    source="GCROC",
                    source_event=4,
                ),
            ]
            name = write_chunk(d, 0, events, 0, config)
            restored = read_events(d / name, {"A", "RC"})
            self.assertEqual(
                (restored[0].key, restored[0].time, restored[0].source_event), (7, 12.5, 3)
            )
            self.assertEqual((restored[1].rc_timestamp, restored[1].time), (2720, 17.0))
            np.testing.assert_array_equal(restored[1].waves["RC"].toa, toa)
            np.testing.assert_array_equal(restored[1].waves["RC"].tot, tot)
            self.assertEqual(len(read_events(d / name, {"RC"}, "GCROC")), 1)

    def test_cached_matching_drains_a_long_tail_without_blocking_other_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            config = test_streaming.StreamingTest.two_inputs(d)
            config.update(raw_dir=str(d), queue_limit=3)
            chunks = [
                {"name": f"{i}.root", "sources": {"BIC:41": 4, "BIC:42": 4}} for i in range(4)
            ]
            (d / "manifest.json").write_text(json.dumps({"chunks": chunks}))
            (d / "decode_status.json").write_text(json.dumps({"status": "complete"}))

            def events(path, capture, source):
                chunk = int(path.stem)
                if source == "BIC:42" and chunk > 0:
                    return []
                name = "A" if source == "BIC:41" else "B"
                return [
                    Event(i, float(i), {name: Wave(i, float(i), np.array([1, 2]))}, source=source)
                    for i in range(chunk * 4, chunk * 4 + 4)
                ]

            pipeline = CachedPipeline(config)
            with patch("matching.cached_pipeline.read_events", side_effect=events):
                for _ in range(100):
                    pipeline.step(final=True)
                    if pipeline.exhausted():
                        break
            self.assertTrue(pipeline.exhausted())
            self.assertEqual(len(pipeline.pending), 4)
            self.assertEqual(pipeline.decoded_total, 20)

    def test_missing_committed_root_is_not_a_complete_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            (d / "decode_status.json").write_text('{"status":"complete"}')
            (d / "manifest.json").write_text('{"chunks":[{"name":"decoded.root","size":3}]}')
            self.assertFalse(complete_cache(d))
            (d / "decoded.root").write_bytes(b"abc")
            self.assertTrue(complete_cache(d))
            (d / "decoded.root").write_bytes(b"a")
            self.assertFalse(complete_cache(d))
