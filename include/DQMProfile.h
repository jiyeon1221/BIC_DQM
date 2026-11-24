#pragma once
#include "../mapping/nkdaq_mapping.h"
#include "../mapping/rcdaq_mapping.h"
#include <cstdlib>
#include <stdexcept>

inline std::string DQM_ProfileName(const char* fallback = "NKDAQ") {
    const char* value = std::getenv("DQM_MAPPING_PROFILE");
    const std::string name = value && *value ? value : fallback;
    if (name != "NKDAQ" && name != "RCDAQ")
        throw std::runtime_error("Unknown DQM_MAPPING_PROFILE: " + name);
    return name;
}

inline const std::vector<DQMMapEntry>& DQM_ProfileEntries(const char* fallback = "NKDAQ") {
    return DQM_ProfileName(fallback) == "RCDAQ" ? RCDAQ_MappingTable() : NKDAQ_MappingTable();
}
