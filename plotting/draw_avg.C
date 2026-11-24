#include "plot_common.h"

namespace DQMPlot {
// Accumulate mean raw ADC per sample without baseline subtraction.
TH1* make_avg(const Plots& p, const std::string& name, int samples) {
    auto daq = p.row(name).daq;
    int nx = std::max(samples, daq == "GCROC" ? 40 : daq == "BIC" ? 120 : daq == "JBNU" ? 240 : 1);
    return new TProfile(histogramName(p, name, "Avg").c_str(),
                        (name + ";Sample index;ADC (raw)").c_str(), nx, -.5, nx - .5);
}

void fill_avg(Plots& p, const std::string& name, const std::vector<short>& wave) {
    auto* h = static_cast<TProfile*>(p.hist(name, "Avg", wave.size()));
    int start = p.row(name).daq == "GCROC" ? 1 : 0;
    for (size_t i = start; i < wave.size(); ++i)
        h->Fill(double(i), wave[i]);
    int& length = p.lengths[{name, "Avg"}];
    length = std::max(length, int(wave.size()));
    h->GetXaxis()->SetRange(start + 1, length);
}

void draw_avg(Plots& p, const Job& job, size_t number) {
    p.drawChannels(job, number, "Avg");
}
}
