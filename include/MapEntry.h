#pragma once
#include <string>

// Shared NKDAQ/RCDAQ mapping schema. Unknown IDs are -1.
// det: SFIL=0, Bulk=1; side: -x=0, +x=1.
// z: SFIL4..8 -> 0..4, Bulk1..6 -> 0..5; y increases upward.
// ch retains each decoder's numbering (NK 1-based, GCROC 0-based).
struct DQMMapEntry {
    std::string daq;
    int mid;
    int ch;
    std::string name;
    int det;
    int side;
    int sma;
    int z;
    int y;
};
