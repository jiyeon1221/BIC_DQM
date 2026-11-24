#!/usr/bin/env bash
_rcdaq_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v root-config >/dev/null 2>&1; then
    # LCG setup reads optional variables and is not compatible with nounset.
    if [[ -o nounset ]]; then
        set +u
        source "${ROOT_SETUP:-/cvmfs/sft.cern.ch/lcg/views/LCG_106/x86_64-el9-gcc13-opt/setup.sh}"
        set -u
    else
        source "${ROOT_SETUP:-/cvmfs/sft.cern.ch/lcg/views/LCG_106/x86_64-el9-gcc13-opt/setup.sh}"
    fi
fi
_rcdaq_deps="${RCDAQ_DEPS_ROOT:-${_rcdaq_dir}/deps/sysroot}"
export ONLINE_MAIN="${_rcdaq_dir}/install"
export PATH="${ONLINE_MAIN}/bin:${_rcdaq_deps}/usr/bin:${PATH}"
export LD_LIBRARY_PATH="${ONLINE_MAIN}/lib:${_rcdaq_deps}/lib64:${_rcdaq_deps}/usr/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
export ROOT_INCLUDE_PATH="${ONLINE_MAIN}/include:${ONLINE_MAIN}/include/Event:${ONLINE_MAIN}/include/pmonitor${ROOT_INCLUDE_PATH:+:${ROOT_INCLUDE_PATH}}"
if [[ -f ${ONLINE_MAIN}/bin/aliases.sh ]]; then
    source "${ONLINE_MAIN}/bin/aliases.sh"
fi
export RCDAQ_DATA_PATH="${RCDAQ_DATA_PATH:-/pnfs/knu.ac.kr/data/eic/user/bgseo/TestBeam/2608CERN/binary/RCDAQ}"
unset _rcdaq_dir _rcdaq_deps
