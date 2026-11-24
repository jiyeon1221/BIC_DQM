#pragma once
// Bind calculated channel data and event identifiers to event_tree branches.
#include <TTree.h>
#include <string>
#include "../processing/waveform_metrics.h"

namespace DQMLive {
struct Record : Features {
    ULong64_t event = 0, nk_trigger = 0, rc_timestamp = 0, source_event = 0;
    double nk_time = 0, delta_us = 0;
    std::string source;

    void bind(TTree& t) {
        t.Branch("event", &event);
        t.Branch("nk_trigger", &nk_trigger);
        t.Branch("rc_timestamp", &rc_timestamp);
        t.Branch("nk_time", &nk_time);
        t.Branch("delta_us", &delta_us);
        t.Branch("source", &source);
        t.Branch("source_event", &source_event);
        t.Branch("toa", &toa);
        t.Branch("tot", &tot);
        t.Branch("adc", &adc);
        t.Branch("offsets", &offsets);
        t.Branch("present", &present);
        t.Branch("usable", &usable);
        t.Branch("baseline", &baseline);
        t.Branch("peak", &peak);
        t.Branch("integral", &integral);
        t.Branch("timestamps", &timestamps);
        t.Branch("triggers", &triggers);
        t.Branch("derived", &derived);
    }
};
}
