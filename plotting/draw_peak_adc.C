#include "plot_common.h"

namespace DQMPlot {
// Plot per-channel PeakADC distributions.
TH1* make_peak_adc(const Plots& p, const std::string& name) {
    auto daq = p.row(name).daq;
    double high = daq == "GCROC" ? 1024 : daq == "NKFADC" ? 4096 : 32768;
    auto* h = new TH1D(histogramName(p, name, "PeakADC").c_str(),
                       (name + ";PeakADC;Events").c_str(), 400, -high * .1, high);
    h->SetCanExtend(TH1::kXaxis);
    return h;
}

void draw_peak_adc(Plots& p, const Job& job, size_t number) {
    p.drawChannels(job, number, "PeakADC");
}
}
