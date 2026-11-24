#!/usr/bin/env bash
set -euo pipefail
build_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ $# -gt 1 || ( $# -eq 1 && $1 != --clean ) ]]; then
    echo "Usage: $0 [--clean]" >&2
    exit 1
fi
source "${build_root}/Setting.sh"
# Build the supplied RCDAQ decoder libraries.
if [[ ${1:-} == --clean ]]; then
    rm -rf -- "${build_root}/decoding/rcdaq/install"
    mkdir -p "${build_root}/decoding/rcdaq/install"
fi
bash "${build_root}/decoding/rcdaq/build.sh"

# Build the ROOT C++ plotters.
cd "${build_root}"
python3 -m plotting.cpp_plotter --force
