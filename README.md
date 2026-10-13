# BIC DQM

CERN 2026 data quality monitoring tools for BIC, NKFADC, and JBNU data. The C++ analysis programs produce ROOT files and waveform GIFs, and the Python server provides a browser interface to run analyses and view the results.

## Requirements

- Linux with Bash and a C++ compiler (`g++`).
- CERN ROOT with `root-config` and the libraries used by `root-config --glibs`. The supplied environment script uses ROOT 6.32.10.
- Python 3. The server uses the Python standard library; no pip packages are required.
- A modern browser and access to the raw binary data. Data and compiled executables are not included in this repository.

## 1. Get the source

```bash
git clone https://github.com/jiyeon1221/BIC_DQM.git
cd BIC_DQM
```

Run the following commands from the repository root unless a section explicitly changes directory.

## 2. Configure the environment

Edit `web/envset.sh` to match your machine:

```bash
#!/bin/bash
source /path/to/root/bin/thisroot.sh
export DQM_DATA_PATH=/path/to/binary
```

Replace both example paths with actual paths. The current defaults in the repository are:

| Setting | Current value |
| --- | --- |
| ROOT setup script | `/home/kobic/Software/Install/root-v6-32-10/bin/thisroot.sh` |
| Raw data directory | `/home/kobic/26CERNData/binary` |

Load the environment in the terminal before compiling or running an analysis:

```bash
source web/envset.sh
root-config --version
command -v g++
python3 --version
ls -ld "$DQM_DATA_PATH"
```

Use `source`, so the environment remains available in the current terminal. Repeat it when opening a new terminal.

The web server also sources `web/envset.sh` when it starts. Set your paths in that file rather than relying only on terminal exports, and restart the server after changing it.

### Input data

Set `DQM_DATA_PATH` to the directory containing the data files themselves. Readers expect these names, with a five-digit run number:

| Reader | Filename pattern | Example for run 790 |
| --- | --- | --- |
| BIC | `Run_<run>_BIC_<MID>.dat` | `Run_00790_BIC_41.dat` |
| NKFADC | `Run_<run>_FADC_<MID>.dat` | `Run_00790_FADC_1.dat` |
| JBNU | `Run_<run>_JBNU_<MID>.dat` | `Run_00790_JBNU_21.dat` |

Channel names and module assignments are defined in `mapping/mapping_CERN2026.h`. Each analysis needs the input files for the selected channels or detectors.

## 3. Compile the analysis programs

After loading the environment, compile every program:

```bash
cd analysis
bash ./compile.sh *.C
cd ..
```

To compile one program or a selection:

```bash
bash analysis/compile.sh draw_peakADC
bash analysis/compile.sh draw_avg draw_heatmap DWC hodoscope
```

Names can be supplied with or without the `.C` extension. The script changes into `analysis/` automatically and creates executables there, such as `analysis/draw_peakADC`. Run it with no arguments to display the available source names:

```bash
bash analysis/compile.sh
```

The no-argument invocation prints usage and exits with status 1. Recompile affected programs after changing analysis sources, headers, or the mapping.

## 4. Start the web interface

For first use, configure the environment and compile all programs as described above. Then start the server:

```bash
python3 web/serve_rootfiles.py --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/** in your browser. Keep the terminal running; press **Ctrl+C** to stop the server.

The server loads its ROOT environment automatically from `web/envset.sh`. Startup messages show the ROOT installation, input data directory, output directory, and DWC calibration status.

For access from another machine on the network:

```bash
python3 web/serve_rootfiles.py --host 0.0.0.0 --port 8000
```

Open `http://<server-ip>:8000/` from the other machine. The server's defaults are `0.0.0.0` and port `8000`. Use a different `--port` if that port is already occupied.

For a remote host accessed through SSH, you can keep the server on `127.0.0.1` and forward the port from your own computer:

```bash
ssh -L 8000:127.0.0.1:8000 <user>@<server>
```

Then open **http://127.0.0.1:8000/** on your own computer.

### Run an analysis in the browser

1. Select the analysis type and method in the command builder.
2. Enter a run number, event settings, and channel or module names from the mapping.
3. Run the generated command and follow its output in the page.
4. Open a generated ROOT or GIF file from the file list to inspect it.

Commands run in `analysis/`, so executable names are entered as `./draw_peakADC`, for example. The file list is initially empty on a fresh clone because generated results are excluded from Git.

Use `serve_rootfiles.py` to start the interface: it provides the command and file APIs used by the page.

## 5. Run analyses from the terminal

Load the environment from the repository root, then change into `analysis/`:

```bash
source web/envset.sh
cd analysis

# Peak ADC for channels CC1 and CC2, using all available events.
./draw_peakADC 790 -1 CC1 CC2

# Average waveform using up to 1000 events.
./draw_avg 790 1000 CC1

# Waveform at a selected event index.
./draw_waveform 790 0 CC1

# Animated waveforms starting at event 0, for 20 events.
./draw_singleWaveform 790 0 20 CC1

# DWC and combined auxiliary plots.
./DWC 790 -1
./draw_AUX 790 -1

# Hodoscope plots.
./hodoscope 790 -1
```

Run numbers and channel names above are examples; use a run present in your data and channels from the mapping. For analyses that take an event count, `-1` processes all available events, except `draw_singleWaveform`, where `-1` means 100 events and the maximum is 100.

Programs run in batch mode by default. Add `-g` to open ROOT canvas windows when a graphical display is available; if `DISPLAY` is unset, the program falls back to batch mode. Run a program without its required arguments to see its usage.

### DWC calibration

DWC position plots use `analysis/DWC_calibration_constants.txt`. Without this file, positions are shown as uncalibrated.

To generate constants, run from `analysis/` with six calibration run numbers:

```text
./DWC_calibration <dwc1LU> <dwc1C> <dwc1RD> <dwc2LU> <dwc2C> <dwc2RD> [posMM=30] [nEvt=-1]
```

Replace the placeholders with the actual calibration runs. This creates `DWC_calibration_constants.txt` and `DWC_calibration_fits.root` in the current directory. To use a different constants file:

```bash
./DWC 790 -1 /path/to/DWC_calibration_constants.txt
./draw_AUX 790 -1 /path/to/DWC_calibration_constants.txt
```

## Output and repository layout

```text
analysis/   C++ analysis sources, compile script, and locally built executables
include/    Shared analysis, data reader, and output headers
mapping/    CERN 2026 channel mapping
web/        Browser interface, JavaScript libraries, environment script, and server
output/     Generated ROOT files and GIFs (created during analysis; ignored by Git)
```

Analysis results normally go to `output/<plot-type>/Run_<run-number>/`. The analysis creates the necessary output directories.

`DQM_OUTPUT_PATH` can override the analysis output directory, but the web server always lists files from this repository's `output/` directory. Leave this variable unset for the standard browser workflow.

Compiled executables, build artifacts, Python caches, and generated output are excluded by `.gitignore`.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `root-config: command not found` or ROOT headers cannot be found | Correct the ROOT setup path in `web/envset.sh`, source it, and confirm `root-config --version` works. |
| `g++: command not found` | Install or load the C++ compiler before compiling. |
| ROOT shared libraries cannot be loaded | Source `web/envset.sh` in the terminal; for browser commands, check the same file and restart the server. |
| An analysis executable is missing | Compile it with `bash analysis/compile.sh <name>`, or compile all sources. |
| `[DAQ] cannot open ...` | Check `DQM_DATA_PATH`, the five-digit run filename, the required MID, and file read permissions. |
| No output files appear in the browser | Run an analysis, inspect its command output, and check that `DQM_OUTPUT_PATH` is unset or points to the repository's `output/`. |
| `Address already in use` | Stop the previous server or choose another port with `--port`. |
| DWC positions are uncalibrated | Generate or provide `DWC_calibration_constants.txt` in `analysis/`, or pass a constants file explicitly. |
