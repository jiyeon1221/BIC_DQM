#!/usr/bin/env bash

# Load the ROOT environment required by DQM.
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
