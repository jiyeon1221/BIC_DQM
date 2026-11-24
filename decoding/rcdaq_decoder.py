"""Connect the supplied RCDAQ packet decoder to incremental input reading."""
from pathlib import Path
import os
from storage.root_writer import root


def rc_decoder():
    R = root()
    online = Path(os.environ["ONLINE_MAIN"])
    if R.gSystem.Load(str(online / "lib/libNoRootEvent.so")) < 0:
        raise RuntimeError("Cannot load RCDAQ decoder")
    R.gInterpreter.AddIncludePath(str(online / "include"))
    if not R.gInterpreter.Declare(
        '#include "' + str(Path(__file__).with_name("rcdaq_buffer_reader.h")) + '"'
    ):
        raise RuntimeError("Cannot load RC stream adapter")
    return R.DQMLive.readRC
