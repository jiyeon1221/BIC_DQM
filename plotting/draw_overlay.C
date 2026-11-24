#include "plot_common.h"

namespace DQMPlot {
// Overlay raw waveforms as a 2D distribution of sample index versus ADC.
TH1* make_overlay(const Plots& p, const std::string& name, int samples) {
    auto daq = p.row(name).daq;
    int nx = std::max(samples, daq == "GCROC" ? 40 : daq == "BIC" ? 120 : daq == "JBNU" ? 240 : 1);
    double high = daq == "GCROC" ? 1024
        : daq == "NKFADC"        ? 4096
                                 : 32768,
           low = (daq == "GCROC" || daq == "NKFADC") ? 0 : -32768;
    return new TH2D(histogramName(p, name, "Overlay").c_str(),
                    (name + ";Sample index;ADC (raw)").c_str(), nx, -.5, nx - .5, 512, low - .5,
                    high - .5);
}

void fill_overlay(Plots& p, const std::string& name, const std::vector<short>& wave) {
    auto* h = static_cast<TH2D*>(p.hist(name, "Overlay", wave.size()));
    int start = p.row(name).daq == "GCROC" ? 1 : 0;
    for (size_t i = start; i < wave.size(); ++i)
        h->Fill(double(i), wave[i]);
    int& length = p.lengths[{name, "Overlay"}];
    length = std::max(length, int(wave.size()));
    h->GetXaxis()->SetRange(start + 1, length);
}

void draw_overlay(Plots& p, const Job& job, size_t number) {
    p.drawChannels(job, number, "Overlay");
}
}
