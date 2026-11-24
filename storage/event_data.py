"""Waveform and event types shared by decoders and matchers."""
from dataclasses import dataclass, field
import numpy as np


@dataclass
class Wave:
    trigger: int
    time: float
    adc: np.ndarray
    toa: object = None
    tot: object = None


@dataclass
class Event:
    key: int
    time: float
    waves: dict = field(default_factory=dict)
    rc_timestamp: int = 0
    delta: float = float("nan")
    rc_adc: object = None
    rc_names: tuple = ()
    rc_toa: object = None
    rc_tot: object = None
    source: str = ""
    source_event: int = 0

    def materialize(self):
        # Expand RC arrays into per-channel Wave objects before storage.
        if self.rc_adc is not None:
            self.waves.update(
                {
                    name: Wave(
                        0,
                        self.time,
                        self.rc_adc[i],
                        self.rc_toa[i] if self.rc_toa is not None else None,
                        self.rc_tot[i] if self.rc_tot is not None else None,
                    )
                    for i, name in enumerate(self.rc_names)
                }
            )
            self.rc_adc = None
            self.rc_toa = None
            self.rc_tot = None
        return self.waves
