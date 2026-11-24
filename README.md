# NKDAQ / RCDAQ DQM

A web interface for plotting test-beam data from NKDAQ and RCDAQ. Select a run,
channels or detector layers, and a plot type in the browser. View completed runs
or monitor incoming data with Live mode.

This guide covers installation and server startup. Run all shell commands from
this directory unless stated otherwise.

## 1. Install

### Requirements

Use a Linux machine with:

- Python 3 with **PyROOT** and **NumPy**.
- ROOT development tools, including `root-config`, and a compatible C++ compiler.
- Boost headers, CMake 3.14 or newer, Make, Autoconf, Automake, and Libtool.
- Development headers/libraries for zlib, bzip2, LZO2, and libtirpc, plus `rpcgen`.
- Read access to the raw data and write access to this checkout and its output directory.

The reference environment is CERN LCG 106 on x86-64 EL9, with ROOT 6.32.02
and GCC 13.1.0. Use Python, PyROOT, and the compiler from the same environment.

On an EL9 machine, the system build dependencies can be installed with:

```bash
sudo dnf install gcc-c++ make cmake autoconf automake libtool \
    boost-devel zlib-devel bzip2-devel lzo-devel libtirpc-devel rpcgen
```

Package availability depends on the enabled distribution repositories. Install
ROOT/PyROOT and NumPy separately, or use the LCG environment below.

### Set up ROOT

If ROOT is already configured, the setup scripts use that installation. Otherwise,
`Setting.sh` sources this default environment:

```text
/cvmfs/sft.cern.ch/lcg/views/LCG_106/x86_64-el9-gcc13-opt/setup.sh
```

On another server, select your ROOT setup script before building:

```bash
export ROOT_SETUP=/path/to/root/bin/thisroot.sh
source Setting.sh
python3 -c 'import ROOT, numpy; print(ROOT.gROOT.GetVersion())'
root-config --version
```

On a machine with the default CVMFS environment, omit the `export ROOT_SETUP` line.
A missing `ROOT` Python module means that Python and ROOT are not configured
consistently; resolve this before proceeding.

### Build

```bash
./build.sh
source web/envset.sh
```

This builds the supplied RCDAQ libraries and the ROOT C++ plotters. Build failures
retain their logs under the `/tmp/rcdaq-build.*` directory printed by the script.

To rebuild the installed RCDAQ libraries and plotters from scratch:

```bash
bash build.sh --clean
```

This does not remove raw data or saved results. Do not rebuild while DQM jobs are running.

The source code needed for RCDAQ is included under `decoding/rcdaq/src/`.
System dependencies are used on a fresh checkout. An existing local dependency
bundle under `decoding/rcdaq/deps/sysroot/` is also supported; use
`RCDAQ_DEPS_ROOT=/absolute/path/to/sysroot` to select another bundle. Compiled
libraries and local dependency bundles are excluded from Git.

### Configure input data

Set both input locations before starting the server:

```bash
export DQM_DATA_PATH=/path/to/binary/NKDAQ
export RCDAQ_DATA_PATH=/path/to/binary/RCDAQ
source web/envset.sh
```

Expected filenames include:

```text
NKDAQ/Run_00790_BIC_41.dat
NKDAQ/Run_00790_FADC_2.dat
RCDAQ/2608CERN_ROC_0-00001088-0000.evt
```

Keep the acquisition filenames. The run number and channel mapping determine
which inputs are opened. An RCDAQ selection may also need NKDAQ inputs for AUX
detectors, as specified by the mapping.

| Environment variable | Purpose | Default |
| --- | --- | --- |
| `ROOT_SETUP` | Environment script used when ROOT is not configured | LCG path shown above |
| `DQM_DATA_PATH` | NKDAQ `.dat` directory | `/pnfs/knu.ac.kr/data/eic/user/bgseo/TestBeam/2608CERN/binary/NKDAQ` |
| `RCDAQ_DATA_PATH` | RCDAQ `.evt` directory | `/pnfs/knu.ac.kr/data/eic/user/bgseo/TestBeam/2608CERN/binary/RCDAQ` |
| `DQM_WEB_OUTPUT_PATH` | Plot output directory | `output/plot/` in this checkout |
| `DQM_DWC_CALIBRATION` | DWC calibration file | `config/dwc_calibration.txt` |
| `RCDAQ_DEPS_ROOT` | Optional dependency sysroot | `decoding/rcdaq/deps/sysroot/` |
| `JOBS` | RCDAQ build parallelism | `4` |

Use absolute paths for environment overrides. The decoded cache is stored in a
`decoded/` directory next to the selected plot output directory.

### Check mapping and calibration

Before using a new detector setup, check:

- [`mapping/nkdaq_mapping.h`](mapping/nkdaq_mapping.h) for the NKDAQ profile.
- [`mapping/rcdaq_mapping.h`](mapping/rcdaq_mapping.h) for the RCDAQ profile.
- [`config/dwc_calibration.txt`](config/dwc_calibration.txt) for the DWC position calibration.
- [`config/aux_cuts.json`](config/aux_cuts.json) for the AUX cut thresholds.

The included calibration contains the current test-beam constants. Replace them
with the appropriate constants for your setup before using DWC positions or cuts.
The web application does not require the separate `analysis/` programs.

## 2. Start the web interface

```bash
source web/envset.sh
python3 web/serve_rootfiles.py --host 127.0.0.1 --port 8000
```

Open **http://localhost:8000/** in a browser on the same machine.

For a remote server, keep the server running and create an SSH tunnel from your
own computer:

```bash
ssh -L 8000:127.0.0.1:8000 USER@SERVER
```

Then open **http://localhost:8000/** on your computer. To allow direct access on a
trusted network, use `--host 0.0.0.0` and open `http://SERVER:8000/` instead. The
interface has no login and allows starting and stopping DQM jobs.

Keep the server terminal open. Restart the server after changing its code or
environment variables; refresh the browser after updating the web interface.
