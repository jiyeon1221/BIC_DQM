#!/usr/bin/env bash
_dqm_web_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "${_dqm_web_root}/Setting.sh"
source "${_dqm_web_root}/decoding/rcdaq/setup.sh"
export DQM_DATA_PATH="${DQM_DATA_PATH:-/pnfs/knu.ac.kr/data/eic/user/bgseo/TestBeam/2608CERN/binary/NKDAQ}"
unset _dqm_web_root
