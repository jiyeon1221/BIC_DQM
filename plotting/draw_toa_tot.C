#include "plot_common.h"

namespace DQMPlot {
// Plot sample index versus positive TOA/TOT codes, following h2gcroc.
TH1* make_toa_tot(const Plots& p, const std::string& name, const std::string& metric) {
    auto* h = new TH2D(histogramName(p, name, metric).c_str(),
                       (name + ";Sample index;" + metric + " (raw code);Counts").c_str(), 40, 0, 40,
                       50, metric == "TOA" ? 1 : -100, metric == "TOA" ? 1024 : 4500);
    h->GetXaxis()->SetRange(1, 20);
    return h;
}

void fill_toa_tot(Plots& p, const std::string& name, const std::string& metric,
                  const std::vector<short>& samples) {
    if (samples.size() < 20)
        return;
    auto* h = static_cast<TH2D*>(p.hist(name, metric));
    for (size_t i = 1; i < samples.size(); ++i)
        if (samples[i] > 0)
            h->Fill(double(i), samples[i]);
    int& length = p.lengths[{name, metric}];
    length = std::max({20, length, int(samples.size())});
    h->GetXaxis()->SetRange(1, length);
}

void draw_toa_tot(Plots& p, const Job& job, size_t number) {
    auto metric = metricFor(job, p.method);
    if (p.method != "TOA/TOT") {
        size_t group = 0;
        for (auto& g : p.groups(job.channels)) {
            Items items;
            for (auto& n : g.second)
                items.push_back({p.hist(n, metric), "COLZ"});
            p.panels("c_" + std::to_string(number) + "_" + job.executable + "_group" +
                         std::to_string(group++),
                     items, g.first + " · " + metric, g.second);
        }
        return;
    }
    Items items;
    std::string title;
    for (auto& name : job.channels) {
        items.push_back({p.hist(name, metric), "COLZ"});
        if (!title.empty())
            title += ", ";
        title += name;
    }
    p.panels("c_" + std::to_string(number) + "_" + job.executable, items, title + " · " + metric,
             {}, std::max(1, int(items.size())));
}
}
